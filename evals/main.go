// Command evals runs light-labs boss fights: each contestant model against a
// stage's fixtures, several samples each, scored deterministically.
//
//	go -C evals run . -stage reply-draft -contestants megaman -samples 3
package main

import (
	"bytes"
	"context"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
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
	names := flag.String("contestants", "megaman", "comma-separated contestant names from contestants.yaml")
	samples := flag.Int("samples", 3, "samples per fixture (local models are nondeterministic)")
	filter := flag.String("filter", "", "only fixtures whose id or category contains one of these comma-separated terms")
	concurrency := flag.Int("concurrency", 1, "parallel samples; keep 1 for local models on a laptop")
	minPass := flag.Float64("min-pass", 0, "exit 1 if any contestant's sample pass rate is below this (0-1)")
	outDir := flag.String("out", "", "write samples as JSONL here (default <repo>/var/evals)")
	timeout := flag.Duration("timeout", 5*time.Minute, "per-sample timeout")
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
	for _, c := range contestants {
		for _, f := range fixtures {
			for n := 1; n <= *samples; n++ {
				jobs = append(jobs, job{c, f, n})
			}
		}
	}
	fmt.Fprintf(os.Stderr, "stage %s: %d fixtures x %d samples x %d contestants = %d runs\n",
		st.Stage, len(fixtures), *samples, len(contestants), len(jobs))

	runID := fmt.Sprintf("%s-%s", st.Stage, time.Now().UTC().Format("20060102T150405Z"))
	commit, dirty := gitState(root)

	results := make([]Sample, len(jobs))
	sem := make(chan struct{}, max(1, *concurrency))
	var wg sync.WaitGroup
	var mu sync.Mutex
	done := 0
	for i, j := range jobs {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, j job) {
			defer wg.Done()
			defer func() { <-sem }()
			ctx, cancel := context.WithTimeout(context.Background(), *timeout)
			defer cancel()
			start := time.Now()
			run, runErr := runSample(ctx, root, st, j.c, j.f)
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
			results[i] = s
			mu.Lock()
			done++
			mark := "."
			if !s.Passed {
				mark = "x"
			}
			fmt.Fprint(os.Stderr, mark)
			if done%50 == 0 || done == len(jobs) {
				fmt.Fprintf(os.Stderr, " %d/%d\n", done, len(jobs))
			}
			mu.Unlock()
		}(i, j)
	}
	wg.Wait()

	dir := *outDir
	if dir == "" {
		dir = filepath.Join(root, "var", "evals")
	}
	path, err := writeResults(dir, runID, results)
	exitOn(err)

	ok := report(os.Stdout, st, contestants, results, *minPass)
	fmt.Printf("\nsamples: %s\n", path)
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
