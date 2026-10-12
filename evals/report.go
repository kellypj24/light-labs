package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"text/tabwriter"
)

// writeResults appends nothing: one JSONL file per run, named by run id.
func writeResults(dir, runID string, samples []Sample) (string, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(dir, runID+".jsonl")
	f, err := os.Create(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	for _, s := range samples {
		if err := enc.Encode(s); err != nil {
			return "", err
		}
	}
	return path, nil
}

type tally struct{ pass, total int }

func (t tally) rate() float64 {
	if t.total == 0 {
		return 0
	}
	return float64(t.pass) / float64(t.total)
}

// report prints per-contestant and per-category pass rates, latency and cost, then
// the fixtures each contestant failed. Returns false if any contestant's sample pass
// rate is below minPass.
func report(w io.Writer, st *Stage, contestants []Contestant, samples []Sample, minPass float64) bool {
	ok := true
	// A sample that never ran is a harness failure, whatever the scores: always fail.
	harnessErrors := 0
	for _, s := range samples {
		if len(s.Checks) > 0 && s.Checks[0].Name == "ran" && !s.Checks[0].Passed {
			harnessErrors++
		}
	}
	if harnessErrors > 0 {
		ok = false
		fmt.Fprintf(w, "\nHARNESS ERRORS: %d samples did not run\n", harnessErrors)
	}
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	fmt.Fprintf(tw, "\nSTAGE %s (robot %s)\n", st.Stage, st.Robot)
	fmt.Fprintln(tw, "contestant\trole\tbrain\tsamples\tfixtures (all samples)\tmean latency\tcost")
	for _, c := range contestants {
		var all tally
		perFixture := map[string]tally{}
		var latency, cost float64
		isolated := true
		for _, s := range samples {
			if s.Contestant != c.Name {
				continue
			}
			all.total++
			pf := perFixture[s.Fixture]
			pf.total++
			if s.Passed {
				all.pass++
				pf.pass++
			}
			perFixture[s.Fixture] = pf
			latency += s.LatencyS
			cost += s.CostUSD
			if s.Isolated != nil && !*s.Isolated {
				isolated = false
			}
		}
		var fx tally
		for _, t := range perFixture {
			fx.total++
			if t.pass == t.total {
				fx.pass++
			}
		}
		note := ""
		if !isolated {
			note = " (not isolated: user CLAUDE.md loaded)"
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\t%d/%d %.0f%%\t%d/%d %.0f%%\t%.1fs\t$%.4f%s\n",
			c.Name, c.Role, c.Brain, all.pass, all.total, 100*all.rate(),
			fx.pass, fx.total, 100*fx.rate(), latency/float64(max(1, all.total)), cost, note)
		if minPass > 0 && all.rate() < minPass {
			ok = false
		}
	}
	tw.Flush()

	cats := map[string]bool{}
	for _, s := range samples {
		cats[s.Category] = true
	}
	var catNames []string
	for k := range cats {
		catNames = append(catNames, k)
	}
	sort.Strings(catNames)
	fmt.Fprintln(tw, "\nby category\t"+joinNames(contestants))
	for _, cat := range catNames {
		row := cat
		for _, c := range contestants {
			var t tally
			for _, s := range samples {
				if s.Contestant == c.Name && s.Category == cat {
					t.total++
					if s.Passed {
						t.pass++
					}
				}
			}
			row += fmt.Sprintf("\t%d/%d", t.pass, t.total)
		}
		fmt.Fprintln(tw, row)
	}
	tw.Flush()

	for _, c := range contestants {
		first := true
		for _, s := range samples {
			if s.Contestant != c.Name || s.Passed {
				continue
			}
			if first {
				fmt.Fprintf(w, "\nfailures: %s\n", c.Name)
				first = false
			}
			fmt.Fprintf(w, "  %s #%d  %s\n", s.Fixture, s.N, failures(s.Checks))
		}
	}
	return ok
}

func joinNames(cs []Contestant) string {
	out := ""
	for i, c := range cs {
		if i > 0 {
			out += "\t"
		}
		out += c.Name
	}
	return out
}
