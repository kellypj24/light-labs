package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
)

// RunResult is the envelope light_labs.evals.run_one prints.
type RunResult struct {
	OK     bool `json:"ok"`
	Result struct {
		Raw      string  `json:"raw"`
		Draft    string  `json:"draft"`
		Escalate *string `json:"escalate"`
	} `json:"result"`
	Stats struct {
		LatencyS     float64  `json:"latency_s"`
		InputTokens  *int     `json:"input_tokens"`
		OutputTokens *int     `json:"output_tokens"`
		CostUSD      *float64 `json:"cost_usd"`
		Isolated     *bool    `json:"isolated,omitempty"`
	} `json:"stats"`
	Error string `json:"error"`
}

// runSample runs one fixture once through the robot's real pipeline in Python.
// A non-zero exit still yields a result when the script printed its envelope.
func runSample(ctx context.Context, root string, st *Stage, c Contestant, f Fixture) (*RunResult, error) {
	payload, err := json.Marshal(map[string]any{
		"stage": st.Stage, "brain": c.Brain, "memory": st.memory, "input": f.Input,
	})
	if err != nil {
		return nil, fmt.Errorf("marshal input: %w", err)
	}
	cmd := exec.CommandContext(ctx, "uv", "run", "--locked", "python", "-m",
		"light_labs.evals.run_one", "--input-json", string(payload))
	cmd.Dir = root
	out, runErr := cmd.Output()
	var res RunResult
	if jsonErr := json.Unmarshal(out, &res); jsonErr == nil {
		return &res, nil
	}
	if ee, ok := runErr.(*exec.ExitError); ok {
		return nil, fmt.Errorf("runner failed: %s", strings.TrimSpace(string(ee.Stderr)))
	}
	if runErr != nil {
		return nil, fmt.Errorf("runner failed: %w", runErr)
	}
	return nil, fmt.Errorf("runner printed no JSON envelope")
}
