package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// RunRecord is <run_id>.run.json: one fight's lifecycle, written at start, after every
// sample, and at the end. A record still "running" with no recent telemetry was killed.
type RunRecord struct {
	RunID         string     `json:"run_id"`
	Stage         string     `json:"stage"`
	Contestants   []string   `json:"contestants"`
	Samples       int        `json:"samples"`
	Filter        string     `json:"filter,omitempty"`
	Commit        string     `json:"commit,omitempty"`
	Dirty         bool       `json:"dirty"`
	Total         int        `json:"total"`
	Done          int        `json:"done"`
	Passed        int        `json:"passed"`
	HarnessErrors int        `json:"harness_errors"`
	CoolPauses    int        `json:"cool_pauses"`
	CoolSeconds   float64    `json:"cool_seconds"`
	CoolAboveC    float64    `json:"cool_above_c,omitempty"`
	Status        string     `json:"status"` // running, completed, cancelled
	Reason        string     `json:"reason,omitempty"`
	StartedAt     time.Time  `json:"started_at"`
	EndedAt       *time.Time `json:"ended_at,omitempty"`
	SamplesFile   string     `json:"samples_file"`
	TelemetryFile string     `json:"telemetry_file"`
	mu            sync.Mutex
	path          string
}

// save writes the record atomically, so a reader never sees half a file.
func (r *RunRecord) save() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	raw, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		return err
	}
	tmp := r.path + ".tmp"
	if err := os.WriteFile(tmp, append(raw, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, r.path)
}

func (r *RunRecord) update(f func(*RunRecord)) {
	r.mu.Lock()
	f(r)
	r.mu.Unlock()
	if err := r.save(); err != nil {
		fmt.Fprintln(os.Stderr, "evals: run record:", err)
	}
}

// Telemetry is one reading of the machine's heat and load. Fields are nil where the
// platform has no reading (Linux in CI has none of the macOS sources).
type Telemetry struct {
	At             time.Time `json:"at"`
	BatteryTempC   *float64  `json:"battery_temp_c,omitempty"`
	BatteryPct     *int      `json:"battery_pct,omitempty"`
	OnAC           *bool     `json:"on_ac,omitempty"`
	CPUSpeedLimit  *int      `json:"cpu_speed_limit,omitempty"` // percent; below 100 means throttled
	ThermalWarning string    `json:"thermal_warning,omitempty"`
	ThermalState   *int      `json:"thermal_state,omitempty"` // NSProcessInfo: 0 nominal .. 3 critical
	Load1          *float64  `json:"load_1,omitempty"`
	OllamaCPU      *float64  `json:"ollama_cpu,omitempty"` // percent of one core, summed
}

var (
	reIoregInt   = regexp.MustCompile(`"(Temperature|CurrentCapacity|ExternalConnected)" = (\w+)`)
	reSpeedLimit = regexp.MustCompile(`CPU_Speed_Limit\s*=\s*(\d+)`)
	reWarning    = regexp.MustCompile(`(?i)thermal warning level\s*(?:set to|=|:)\s*(\w+)`)
	reLoad       = regexp.MustCompile(`\{\s*([\d.]+)`)
)

// parseBattery reads `ioreg -rn AppleSmartBattery`. Temperature is in centi-degrees C.
func parseBattery(out string, t *Telemetry) {
	for _, m := range reIoregInt.FindAllStringSubmatch(out, -1) {
		switch m[1] {
		case "Temperature":
			if v, err := strconv.Atoi(m[2]); err == nil {
				c := float64(v) / 100
				t.BatteryTempC = &c
			}
		case "CurrentCapacity":
			if v, err := strconv.Atoi(m[2]); err == nil {
				t.BatteryPct = &v
			}
		case "ExternalConnected":
			ac := m[2] == "Yes"
			t.OnAC = &ac
		}
	}
}

// parseTherm reads `pmset -g therm`: no limit recorded means full speed.
func parseTherm(out string, t *Telemetry) {
	limit := 100
	if m := reSpeedLimit.FindStringSubmatch(out); m != nil {
		limit, _ = strconv.Atoi(m[1])
	}
	t.CPUSpeedLimit = &limit
	if m := reWarning.FindStringSubmatch(out); m != nil {
		t.ThermalWarning = m[1]
	}
}

// parseOllamaCPU sums %CPU of Ollama's processes from `ps -Ao pcpu,comm`.
func parseOllamaCPU(out string) *float64 {
	total, seen := 0.0, false
	for _, line := range strings.Split(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 || !strings.Contains(strings.ToLower(line), "ollama") &&
			!strings.Contains(line, "llama-server") {
			continue
		}
		if v, err := strconv.ParseFloat(fields[0], 64); err == nil {
			total, seen = total+v, true
		}
	}
	if !seen {
		return nil
	}
	return &total
}

func readTelemetry() Telemetry {
	t := Telemetry{At: time.Now().UTC()}
	run := func(name string, args ...string) string {
		out, err := exec.Command(name, args...).Output()
		if err != nil {
			return ""
		}
		return string(out)
	}
	parseBattery(run("ioreg", "-rn", "AppleSmartBattery"), &t)
	if out := run("pmset", "-g", "therm"); out != "" {
		parseTherm(out, &t)
	}
	if m := reLoad.FindStringSubmatch(run("sysctl", "-n", "vm.loadavg")); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			t.Load1 = &v
		}
	}
	t.OllamaCPU = parseOllamaCPU(run("ps", "-Ao", "pcpu,comm"))
	js := `ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState`
	if v, err := strconv.Atoi(strings.TrimSpace(run("osascript", "-l", "JavaScript", "-e", js))); err == nil {
		t.ThermalState = &v
	}
	return t
}

// Monitor samples telemetry on an interval into a JSONL file and keeps the latest.
type Monitor struct {
	mu     sync.Mutex
	latest Telemetry
	read   func() Telemetry
}

func (m *Monitor) Latest() Telemetry {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.latest
}

func (m *Monitor) sample(f *os.File) {
	t := m.read()
	m.mu.Lock()
	m.latest = t
	m.mu.Unlock()
	if f != nil {
		if raw, err := json.Marshal(t); err == nil {
			f.Write(append(raw, '\n'))
		}
	}
}

// Run samples now and then every interval until ctx ends.
func (m *Monitor) Run(ctx context.Context, f *os.File, every time.Duration) {
	m.sample(f)
	tick := time.NewTicker(every)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			m.sample(f)
		}
	}
}

// hot says why the machine should cool before the next sample, or "" if it needn't.
func hot(t Telemetry, coolAbove float64) string {
	if coolAbove <= 0 {
		return ""
	}
	if t.ThermalState != nil && *t.ThermalState >= 2 {
		return fmt.Sprintf("thermal state %d (serious or worse)", *t.ThermalState)
	}
	if t.CPUSpeedLimit != nil && *t.CPUSpeedLimit < 100 {
		return fmt.Sprintf("CPU throttled to %d%%", *t.CPUSpeedLimit)
	}
	if t.BatteryTempC != nil && *t.BatteryTempC > coolAbove {
		return fmt.Sprintf("battery %.1f°C > %.0f°C", *t.BatteryTempC, coolAbove)
	}
	return ""
}

// coolDown waits while the machine is hot, re-reading every `step`, up to maxWait.
// Returns the seconds waited (0 if it didn't wait) and, if still hot at maxWait, why.
func coolDown(ctx context.Context, m *Monitor, coolAbove float64, step, maxWait time.Duration) (float64, string) {
	start := time.Now()
	for {
		why := hot(m.Latest(), coolAbove)
		if why == "" {
			return time.Since(start).Seconds(), ""
		}
		if time.Since(start) >= maxWait {
			return time.Since(start).Seconds(), why
		}
		fmt.Fprintf(os.Stderr, "  cooling: %s; waiting %s\n", why, step)
		select {
		case <-ctx.Done():
			return time.Since(start).Seconds(), ""
		case <-time.After(step):
			m.sample(nil)
		}
	}
}

// scoreboard is a running pass count per contestant, in contestant order.
type scoreboard struct {
	order  []string
	passed map[string]int
	done   map[string]int
}

func newScoreboard(names []string) *scoreboard {
	return &scoreboard{order: names, passed: map[string]int{}, done: map[string]int{}}
}

func (t *scoreboard) add(name string, ok bool) {
	t.done[name]++
	if ok {
		t.passed[name]++
	}
}

func (t *scoreboard) String() string {
	var parts []string
	for _, n := range t.order {
		if d := t.done[n]; d > 0 {
			parts = append(parts, fmt.Sprintf("%s %d/%d %d%%", n, t.passed[n], d, 100*t.passed[n]/d))
		}
	}
	return strings.Join(parts, ", ")
}

func clock(d time.Duration) string {
	d = d.Round(time.Second)
	return fmt.Sprintf("%d:%02d", int(d.Minutes()), int(d.Seconds())%60)
}

// progressLine is the per-sample line: where the fight is, how each contestant is
// doing, how long is left, and how warm the machine is.
func progressLine(done, total int, s Sample, t *scoreboard, elapsed time.Duration, tel Telemetry) string {
	mark := "pass"
	if !s.Passed {
		mark = "FAIL"
	}
	eta := time.Duration(float64(elapsed) / float64(done) * float64(total-done))
	heat := ""
	if tel.BatteryTempC != nil {
		heat = fmt.Sprintf(" | %.1f°C", *tel.BatteryTempC)
	}
	if tel.CPUSpeedLimit != nil && *tel.CPUSpeedLimit < 100 {
		heat += fmt.Sprintf(" throttled %d%%", *tel.CPUSpeedLimit)
	}
	return fmt.Sprintf("[%3d/%d] %-11s %-28s #%d %s %5.1fs | %s | %s, ~%s left%s",
		done, total, s.Contestant, s.Fixture, s.N, mark, s.LatencyS, t, clock(elapsed),
		clock(eta), heat)
}
