package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseReadings(t *testing.T) {
	var tel Telemetry
	parseBattery(`  "CurrentCapacity" = 13
  "ExternalConnected" = No
  "Temperature" = 3033`, &tel)
	if tel.BatteryTempC == nil || *tel.BatteryTempC != 30.33 || *tel.BatteryPct != 13 || *tel.OnAC {
		t.Fatalf("battery: %+v", tel)
	}
	parseTherm("Note: No thermal warning level has been recorded\n", &tel)
	if *tel.CPUSpeedLimit != 100 {
		t.Fatalf("no limit recorded means full speed, got %d", *tel.CPUSpeedLimit)
	}
	parseTherm("CPU Power notify\n\tCPU_Scheduler_Limit \t= 100\n\tCPU_Available_CPUs \t= 10\n\tCPU_Speed_Limit \t= 72\n", &tel)
	if *tel.CPUSpeedLimit != 72 {
		t.Fatalf("speed limit: %d", *tel.CPUSpeedLimit)
	}
	cpu := parseOllamaCPU(" %CPU COMM\n265.2 /Applications/Ollama.app/Contents/Resources/llama-server\n  1.0 /Applications/Ollama.app/Contents/MacOS/Ollama\n 5.6 WindowServer\n")
	if cpu == nil || *cpu != 266.2 {
		t.Fatalf("ollama cpu: %v", cpu)
	}
	if parseOllamaCPU(" %CPU COMM\n 5.6 WindowServer\n") != nil {
		t.Fatal("no ollama process should read as nil")
	}
}

func TestHot(t *testing.T) {
	c, limit := 41.0, 100
	tel := Telemetry{BatteryTempC: &c, CPUSpeedLimit: &limit}
	if hot(tel, 0) != "" {
		t.Fatal("cooling off by default")
	}
	if !strings.Contains(hot(tel, 40), "battery 41.0°C") {
		t.Fatalf("hot battery: %q", hot(tel, 40))
	}
	cool, throttled := 35.0, 80
	if !strings.Contains(hot(Telemetry{BatteryTempC: &cool, CPUSpeedLimit: &throttled}, 40), "throttled") {
		t.Fatal("a throttled CPU should cool even when the battery is cool")
	}
	if hot(Telemetry{}, 40) != "" {
		t.Fatal("no readings (CI) should never wait")
	}
}

func TestCoolDownWaitsUntilCool(t *testing.T) {
	temps := []float64{45, 42, 38}
	i := 0
	m := &Monitor{read: func() Telemetry {
		c := temps[min(i, len(temps)-1)]
		i++
		return Telemetry{BatteryTempC: &c}
	}}
	m.sample(nil)
	waited := coolDown(context.Background(), m, 40, time.Millisecond, time.Second)
	if i < 3 || waited <= 0 {
		t.Fatalf("should re-read until below 40: reads=%d waited=%v", i, waited)
	}
}

func TestProgressLine(t *testing.T) {
	sb := newScoreboard([]string{"mega-man", "proto"})
	sb.add("mega-man", true)
	sb.add("mega-man", false)
	c := 33.4
	line := progressLine(2, 8, Sample{Contestant: "mega-man", Fixture: "chat_joke", N: 2, LatencyS: 1.2},
		sb, 20*time.Second, Telemetry{BatteryTempC: &c})
	for _, want := range []string{"[  2/8]", "FAIL", "mega-man 1/2 50%", "0:20, ~1:00 left", "33.4°C"} {
		if !strings.Contains(line, want) {
			t.Errorf("progress line %q missing %q", line, want)
		}
	}
}

func TestRunRecordSave(t *testing.T) {
	path := filepath.Join(t.TempDir(), "r.run.json")
	rec := &RunRecord{RunID: "r", Status: "running", Total: 4, path: path}
	rec.update(func(r *RunRecord) { r.Done = 2 })
	var got map[string]any
	raw, _ := os.ReadFile(path)
	if err := json.Unmarshal(raw, &got); err != nil || got["done"].(float64) != 2 || got["status"] != "running" {
		t.Fatalf("record: %s", raw)
	}
}
