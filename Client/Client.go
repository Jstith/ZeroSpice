package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Server   string
	Username string
	Node     string
	VMID     int
	Session  string
}

type VM struct {
	Name string `json:"name"`
	Node string `json:"node"`
	Type string `json:"type"`
	VMID int    `json:"vmid"`
}

func main() {

	config, err := parseInput()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		fmt.Fprintf(os.Stderr, "\nUsage:\n")
		flag.PrintDefaults()
		os.Exit(1)
	}
	fmt.Println("[*] Passed argument validation")

	err = checkServerHealth(config)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("[*] Passed server health check")

	err = authenticateUser(config)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// Once acquired, refreshes JWT every 10 minutes, server timeout is 15 minutes
	go func() {
		ticker := time.NewTicker(10 * time.Minute)
		defer ticker.Stop()
		for range ticker.C {
			err = refreshToken(config)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
		}
	}()

	// Node and VMID specified in CLI arguments
	if config.VMID != -1 && config.Node != "" {
		spiceText, err := getSpiceFile(config)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		}

		err = runSpiceFile(spiceText)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		}
	}

	for true {
		vms, err := getVMs(config)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		vmid, node, err := selectVM(vms)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		config.VMID = vmid
		config.Node = node

		spiceText, err := getSpiceFile(config)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		}

		err = runSpiceFile(spiceText)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		}
	}

}

func parseInput() (*Config, error) {
	server := flag.String("server", "", "Domain or IP of the ZeroSpice Server")
	username := flag.String("username", "", "The username used to authenticate to the server")
	node := flag.String("node", "", "(Optional) The Proxmox node to access")
	vmid := flag.Int("vmid", -1, "(Optional) The VMID to access")

	flag.Parse()

	var argErrors []string

	if *server == "" {
		argErrors = append(argErrors, "server is required")
	}
	if *username == "" {
		argErrors = append(argErrors, "username is required")
	}
	// if *node == "" {
	// 	argErrors = append(argErrors, "node is required")
	// }
	// if *vmid == -1 {
	// 	argErrors = append(argErrors, "vmid is required")
	// }
	if len(flag.Args()) > 0 {
		argErrors = append(argErrors, fmt.Sprintf("Unknown arguments: %v", flag.Args()))
	}

	if len(argErrors) > 0 {
		return nil, fmt.Errorf("validation failed: %s", strings.Join(argErrors, ": "))
	}

	return &Config{
		Server:   *server,
		Username: *username,
		Node:     *node,
		VMID:     *vmid,
		Session:  "",
	}, nil
}

func checkServerHealth(config *Config) error {
	url := config.Server + "/health"
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("failed to connect to %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("Health check failed for %s", url)
	}
	return nil
}

func authenticateUser(config *Config) error {
	url := config.Server + "/login"

	reader := bufio.NewReader(os.Stdin)
	fmt.Printf("[>] Enter OTP for %s: ", config.Username)
	otp, _ := reader.ReadString('\n')
	otp = strings.TrimSpace(otp)
	matched, err := regexp.MatchString(`^\d{6}$`, otp)
	if err != nil || !matched {
		return fmt.Errorf("Invalid OTP format")
	}

	requestBody := map[string]interface{}{
		"username":  config.Username,
		"totp_code": otp,
	}
	jsonData, _ := json.Marshal(requestBody)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Post(url, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to post auth request: %w", err)
	}
	defer resp.Body.Close()

	var retData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&retData)

	token, ok := retData["token"].(string)
	if !ok {
		return fmt.Errorf("session token not found authentication response")
	}

	config.Session = token
	return nil
}

func refreshToken(config *Config) error {

	url := config.Server + "/refresh"
	req, err := http.NewRequest("POST", url, nil)
	if err != nil {
		return fmt.Errorf("error making http request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+config.Session)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to request token refresh: %v", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("could not parse token refresh response body: %v", err)
	}
	var tokenReply struct {
		Token string `json:"token"`
	}
	err = json.Unmarshal(body, &tokenReply)
	if err != nil {
		return fmt.Errorf("could not parse refreshed token from response body: %v", err)
	}
	config.Session = tokenReply.Token
	return nil
}

func getVMs(config *Config) ([]VM, error) {
	url := config.Server + "/offer"
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("error making http request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+config.Session)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch available VMs: %v", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("could not parse response body: %v", err)
	}

	var vms []VM
	err = json.Unmarshal([]byte(body), &vms)
	if err != nil {
		return nil, fmt.Errorf("invalid json returned by server: %v", err)
	}
	return vms, nil
}

func selectVM(vms []VM) (int, string, error) {
	fmt.Println("\nNAME\t\tVMID\tNODE\tTYPE")
	for _, vm := range vms {
		fmt.Printf("%s\t%d\t%s\t%s\n", vm.Name, vm.VMID, vm.Node, vm.Type)
	}
	fmt.Printf("\nOr enter \"quit\" to exit the program.\n\n")
	reader := bufio.NewReader(os.Stdin)
	fmt.Printf("[>] Select VMID: ")
	vmid, _ := reader.ReadString('\n')
	vmid = strings.TrimSpace(vmid)
	if vmid == "quit" {
		fmt.Printf("Exiting...")
		os.Exit(0)
	}
	for _, vm := range vms {
		comp := strconv.Itoa(vm.VMID)
		if comp == vmid {
			return vm.VMID, vm.Node, nil
		}
	}
	return -1, "", fmt.Errorf("vm not found for id %s", vmid)
}

func getSpiceFile(config *Config) (string, error) {
	url := config.Server + "/spice/" + config.Node + "/" + strconv.Itoa(config.VMID)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("error making http request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+config.Session)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to fetch spice file: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("could not parse spice body: %v", err)
	}

	return string(body), nil
}

func runSpiceFile(spiceText string) error {

	spiceFile, err := os.CreateTemp("", "spice.vv")
	if err != nil {
		return fmt.Errorf("Failed to create temp file: %v", err)
	}
	defer os.Remove(spiceFile.Name())

	_, err = spiceFile.Write([]byte(spiceText))
	if err != nil {
		return fmt.Errorf("failed to write spice contents to temp file: %v", err)
	}

	cmd := exec.Command("remote-viewer", spiceFile.Name())
	_, err = cmd.CombinedOutput()
	if err != nil {
		spiceFile.Close()
		return fmt.Errorf("Failed to run remote-viewer command (linux): %v", err)
	}
	spiceFile.Close()
	return nil
}
