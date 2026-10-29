// Command evals runs light-labs boss fights: each contestant model against a
// stage's fixtures, several samples each, scored deterministically.
//
//	go -C evals run . -stage reply-draft -contestants mega-man -samples 3
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Sample is one scored run of one fixture by one contestant.
type Sample struct {
	RunID  string `json:"run_id"`
	Commit string `json:"commit,omitempty"`
	Dirty  bool   `json:"dirty"`
	Filter string `json:"filter,omitempty"`
	// The stage's bar when the run was made, so a later change can't rewrite history.
	BarMinFixtureRate *float64  `json:"bar_min_fixture_rate,omitempty"`
	BarMaxGap         *float64  `json:"bar_max_gap,omitempty"`
	Contestant        string    `json:"contestant"`
	Role              string    `json:"role"`
	Brain             string    `json:"brain"`
	Stage             string    `json:"stage"`
	Fixture           string    `json:"fixture"`
	Category          string    `json:"category"`
	N                 int       `json:"sample"`
	Passed            bool      `json:"passed"`
	Checks            []Check   `json:"checks"`
	Draft             string    `json:"draft"`
	Escalate          string    `json:"escalate,omitempty"`
	LatencyS          float64   `json:"latency_s"`
	CostUSD           float64   `json:"cost_usd"`
	Isolated          *bool     `json:"isolated,omitempty"`
	Error             string    `json:"error,omitempty"`
	At                time.Time `json:"at"`
}

func main() {
	stageName := flag.String("stage", "reply-draft", "stage to fight (evals/stages/<stage>.yaml)")
	names := flag.String("contestants", "mega-man", "comma-separated contestant names from contestants.yaml")
	samples := flag.Int("samples", 3, "samples per fixture (local models are nondeterministic)")
	filter := flag.String("filter", "", "only fixtures whose id or category contains one of these comma-separated terms")
	concurrency := flag.Int("concurrency", 1, "parallel samples; keep 1 for local models on a laptop")
	minPass := flag.Float64("min-pass", 0, "exit 1 if any contestant's sample pass rate is below this (0-1)")
	outDir := flag.String("out", "", "write samples as JSONL here (default <repo>/var/evals)")
	timeout := flag.Duration("timeout", 5*time.Minute, "per-sample timeout")
	coolAbove := flag.Float64("cool-above", 40, "pause before a sample while the battery is above this many °C or the CPU is throttled (0: off)")
	coolMaxWait := flag.Duration("cool-max-wait", 10*time.Minute, "longest single cooling pause; still hot after it stops the fight")
	telemetryEvery := flag.Duration("telemetry-every", 30*time.Second, "how often to read heat and load")
	flag.Parse()

	evalsDir, _ := os.Getwd()
	root := filepath.Dir(evalsDir)

	st, err := loadStage(evalsDir, *stageName)
	exitOn(err)
	all, err := loadContestants(evalsDir)
	exitOn(err)

	var contestants []Contestant
	for _, n := range strings.Split(*names, ",") {
		c, ok := all[strings.TrimSpace(n)]
		if !ok {
			exitOn(fmt.Errorf("unknown contestant %q (see contestants.yaml)", n))
		}
		contestants = append(contestants, c)
	}
	var fixtures []Fixture
	for _, f := range st.Fixtures {
		if matches(f, *filter) {
			fixtures = append(fixtures, f)
		}
	}
	if len(fixtures) == 0 {
		exitOn(fmt.Errorf("no fixtures match %q", *filter))
	}

	type job struct {
		c Contestant
		f Fixture
		n int
	}
	var jobs []job
	var contestantNames []string
	for _, c := range contestants {
		contestantNames = append(contestantNames, c.Name)
		for _, f := range fixtures {
			for n := 1; n <= *samples; n++ {
				jobs = append(jobs, job{c, f, n})
			}
		}
	}

	runID := fmt.Sprintf("%s-%s", st.Stage, time.Now().UTC().Format("20060102T150405Z"))
	commit, dirty := gitState(root)
	dir := *outDir
	if dir == "" {
		dir = filepath.Join(root, "var", "evals")
	}
	exitOn(os.MkdirAll(dir, 0o755))

	// Ctrl-C or SIGTERM stops new samples, cancels the running ones, and still writes
	// the record and the partial report.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	samplesPath := filepath.Join(dir, runID+".jsonl")
	samplesFile, err := os.Create(samplesPath)
	exitOn(err)
	defer samplesFile.Close()
	telemetryPath := filepath.Join(dir, runID+".telemetry.jsonl")
	telemetryFile, err := os.Create(telemetryPath)
	exitOn(err)
	defer telemetryFile.Close()

	rec := &RunRecord{RunID: runID, Stage: st.Stage, Contestants: contestantNames, Samples: *samples,
		Filter: *filter, Commit: commit, Dirty: dirty, Total: len(jobs), Status: "running",
		StartedAt: time.Now().UTC(), SamplesFile: samplesPath, TelemetryFile: telemetryPath,
		CoolAboveC: *coolAbove, path: filepath.Join(dir, runID+".run.json")}
	exitOn(rec.save())

	monitor := &Monitor{read: readTelemetry}
	monCtx, stopMonitor := context.WithCancel(context.Background())
	go monitor.Run(monCtx, telemetryFile, *telemetryEvery)
	defer stopMonitor()

	fmt.Fprintf(os.Stderr, "stage %s: %d fixtures x %d samples x %d contestants = %d runs\n",
		st.Stage, len(fixtures), *samples, len(contestants), len(jobs))
	fmt.Fprintf(os.Stderr, "run %s (watch: uv run lab evals watch)\n", runID)

	results := make([]Sample, len(jobs))
	sem := make(chan struct{}, max(1, *concurrency))
	var wg sync.WaitGroup
	var mu sync.Mutex
	enc := json.NewEncoder(samplesFile)
	scores := newScoreboard(contestantNames)
	started := time.Now()
	done := 0
	tooHot := ""
	for i, j := range jobs {
		if ctx.Err() != nil {
			break
		}
		waited, still := coolDown(ctx, monitor, *coolAbove, 30*time.Second, *coolMaxWait)
		if waited >= 1 {
			rec.update(func(r *RunRecord) { r.CoolPauses++; r.CoolSeconds += waited })
		}
		if still != "" {
			tooHot = fmt.Sprintf("too hot: %s after %s", still, *coolMaxWait)
			fmt.Fprintln(os.Stderr, "  stopping:", tooHot)
			break
		}
		if ctx.Err() != nil {
			break
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, j job) {
			defer wg.Done()
			defer func() { <-sem }()
			sampleCtx, cancel := context.WithTimeout(ctx, *timeout)
			defer cancel()
			start := time.Now()
			run, runErr := runSample(sampleCtx, root, st, j.c, j.f)
			if ctx.Err() != nil {
				return // interrupted mid-sample: not a result
			}
			s := Sample{RunID: runID, Commit: commit, Dirty: dirty, Filter: *filter, Contestant: j.c.Name, Role: j.c.Role, Brain: j.c.Brain, Stage: st.Stage,
				Fixture: j.f.ID, Category: j.f.Category, N: j.n, At: start.UTC()}
			if runErr != nil {
				s.Error = runErr.Error()
				s.Checks = []Check{{Name: "ran", Detail: runErr.Error()}}
			} else {
				s.Checks = score(run, j.f.Expect)
				s.Draft = run.Result.Draft
				if run.Result.Escalate != nil {
					s.Escalate = *run.Result.Escalate
				}
				s.LatencyS = run.Stats.LatencyS
				if run.Stats.CostUSD != nil {
					s.CostUSD = *run.Stats.CostUSD
				}
				s.Isolated = run.Stats.Isolated
				s.Error = run.Error
			}
			if st.Bar != nil {
				s.BarMinFixtureRate, s.BarMaxGap = &st.Bar.MinFixtureRate, &st.Bar.MaxGap
			}
			s.Passed = passed(s.Checks)

			mu.Lock()
			defer mu.Unlock()
			results[i] = s
			if err := enc.Encode(s); err != nil { // saved as it finishes
				fmt.Fprintln(os.Stderr, "evals: write sample:", err)
			}
			done++
			scores.add(s.Contestant, s.Passed)
			harness := !s.Passed && len(s.Checks) > 0 && s.Checks[0].Name == "ran" && !s.Checks[0].Passed
			rec.update(func(r *RunRecord) {
				r.Done = done
				if s.Passed {
					r.Passed++
				}
				if harness {
					r.HarnessErrors++
				}
			})
			fmt.Fprintln(os.Stderr, progressLine(done, len(jobs), s, scores, time.Since(started), monitor.Latest()))
		}(i, j)
	}
	wg.Wait()
	stopMonitor()

	var finished []Sample
	for _, s := range results {
		if s.RunID != "" {
			finished = append(finished, s)
		}
	}
	ended := time.Now().UTC()
	cancelled := ctx.Err() != nil || tooHot != ""
	rec.update(func(r *RunRecord) {
		r.EndedAt = &ended
		r.Status = "completed"
		if cancelled {
			r.Status, r.Reason = "cancelled", "interrupted"
			if tooHot != "" {
				r.Reason = tooHot
			}
		}
	})
	if cancelled {
		fmt.Fprintf(os.Stderr, "\ncancelled after %d/%d samples; add a reason: uv run lab evals cancel %s --reason \"...\"\n",
			len(finished), len(jobs), runID)
	}
	if len(finished) == 0 {
		os.Exit(130)
	}

	ok := report(os.Stdout, st, contestants, finished, *minPass)
	fmt.Printf("\nsamples: %s\n", samplesPath)
	if cancelled {
		os.Exit(130)
	}
	if !ok {
		os.Exit(1)
	}
}

// gitState records which code produced a run: prompts and skills change between runs.
func gitState(root string) (commit string, dirty bool) {
	out, err := exec.Command("git", "-C", root, "rev-parse", "--short", "HEAD").Output()
	if err != nil {
		return "", false
	}
	status, _ := exec.Command("git", "-C", root, "status", "--porcelain").Output()
	return strings.TrimSpace(string(out)), len(bytes.TrimSpace(status)) > 0
}

func exitOn(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "evals:", err)
		os.Exit(2)
	}
}

// matches reports whether a fixture's id or category contains any comma-separated term.
func matches(f Fixture, filter string) bool {
	if filter == "" {
		return true
	}
	for _, term := range strings.Split(filter, ",") {
		if term = strings.TrimSpace(term); term != "" &&
			(strings.Contains(f.ID, term) || strings.Contains(f.Category, term)) {
			return true
		}
	}
	return false
}
