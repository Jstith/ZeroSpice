package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"time"
)

// VM represents a virtual machine from the server
type VM struct {
	Name string `json:"name"`
	Node string `json:"node"`
	Type string `json:"type"`
	VMID int    `json:"vmid"`
}

// Client manages communication with the ZeroSpice server
type Client struct {
	ServerURL    string
	Username     string
	SessionToken string
	httpClient   *http.Client
}

// NewClient creates a new ZeroSpice client
func NewClient(serverURL string) *Client {
	return &Client{
		ServerURL: serverURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// CheckServerHealth verifies the server is reachable and healthy
func (c *Client) CheckServerHealth() error {
	url := c.ServerURL + "/health"
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return fmt.Errorf("failed to connect to %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("health check failed for %s", url)
	}
	return nil
}

// Authenticate performs TOTP-based authentication and stores the session token
func (c *Client) Authenticate(username, otp string) error {
	// Validate OTP format
	matched, err := regexp.MatchString(`^\d{6}$`, otp)
	if err != nil || !matched {
		return fmt.Errorf("invalid OTP format (must be 6 digits)")
	}

	url := c.ServerURL + "/login"
	requestBody := map[string]interface{}{
		"username":  username,
		"totp_code": otp,
	}
	jsonData, _ := json.Marshal(requestBody)

	resp, err := c.httpClient.Post(url, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to post auth request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		var errData map[string]interface{}
		json.NewDecoder(resp.Body).Decode(&errData)
		if errMsg, ok := errData["error"].(string); ok {
			return fmt.Errorf("authentication failed: %s", errMsg)
		}
		return fmt.Errorf("authentication failed with status %d", resp.StatusCode)
	}

	var retData map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&retData); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	token, ok := retData["token"].(string)
	if !ok {
		return fmt.Errorf("session token not found in authentication response")
	}

	c.SessionToken = token
	c.Username = username
	return nil
}

// RefreshToken refreshes the current session token
func (c *Client) RefreshToken() error {
	if c.SessionToken == "" {
		return fmt.Errorf("no session token to refresh")
	}

	url := c.ServerURL + "/refresh"
	req, err := http.NewRequest("POST", url, nil)
	if err != nil {
		return fmt.Errorf("error making http request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.SessionToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to request token refresh: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("token refresh failed with status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("could not parse token refresh response body: %w", err)
	}

	var tokenReply struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(body, &tokenReply); err != nil {
		return fmt.Errorf("could not parse refreshed token from response body: %w", err)
	}

	c.SessionToken = tokenReply.Token
	return nil
}

// GetVMs retrieves the list of available VMs from the server
func (c *Client) GetVMs() ([]VM, error) {
	if c.SessionToken == "" {
		return nil, fmt.Errorf("not authenticated")
	}

	url := c.ServerURL + "/offer"
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("error making http request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.SessionToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch available VMs: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == 401 {
		return nil, fmt.Errorf("authentication expired, please login again")
	}

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("failed to fetch VMs with status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("could not parse response body: %w", err)
	}

	var vms []VM
	if err := json.Unmarshal(body, &vms); err != nil {
		return nil, fmt.Errorf("invalid json returned by server: %w", err)
	}

	return vms, nil
}

// GetSpiceFile retrieves the SPICE connection file for a specific VM
func (c *Client) GetSpiceFile(node string, vmid int) (string, error) {
	if c.SessionToken == "" {
		return "", fmt.Errorf("not authenticated")
	}

	url := fmt.Sprintf("%s/spice/%s/%d", c.ServerURL, node, vmid)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("error making http request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.SessionToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to fetch spice file: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == 401 {
		return "", fmt.Errorf("authentication expired, please login again")
	}

	if resp.StatusCode != 200 {
		return "", fmt.Errorf("failed to fetch SPICE file with status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("could not parse spice body: %w", err)
	}

	return string(body), nil
}

// LaunchSpiceViewer writes the SPICE file and launches the appropriate viewer
func (c *Client) LaunchSpiceViewer(spiceText string) error {
	spiceFile, err := os.CreateTemp("", "spice-*.vv")
	if err != nil {
		return fmt.Errorf("failed to create temp file: %w", err)
	}
	defer os.Remove(spiceFile.Name())

	_, err = spiceFile.Write([]byte(spiceText))
	if err != nil {
		spiceFile.Close()
		return fmt.Errorf("failed to write spice contents to temp file: %w", err)
	}
	spiceFile.Close()

	// Use appropriate viewer command based on OS
	viewerCmd := "remote-viewer"
	if runtime.GOOS == "windows" {
		viewerCmd = "virt-viewer"
	}

	cmd := exec.Command(viewerCmd, spiceFile.Name())
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to run %s: %w (ensure %s is installed)", viewerCmd, err, viewerCmd)
	}

	return nil
}

// StartTokenRefreshLoop starts a goroutine that refreshes the token every 10 minutes
// Returns a channel that can be closed to stop the refresh loop
func (c *Client) StartTokenRefreshLoop() chan struct{} {
	stopChan := make(chan struct{})

	go func() {
		ticker := time.NewTicker(10 * time.Minute)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				if err := c.RefreshToken(); err != nil {
					fmt.Fprintf(os.Stderr, "Error refreshing token: %v\n", err)
					return
				}
			case <-stopChan:
				return
			}
		}
	}()

	return stopChan
}
