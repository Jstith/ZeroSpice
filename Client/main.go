package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

func main() {
	// Parse command line flags
	server := flag.String("server", "", "Domain or IP of the ZeroSpice Server")
	username := flag.String("username", "", "The username used to authenticate to the server")
	node := flag.String("node", "", "(Optional) The Proxmox node to access")
	vmid := flag.Int("vmid", -1, "(Optional) The VMID to access")
	guiMode := flag.Bool("gui", false, "Launch GUI mode")

	flag.Parse()

	// Check for unknown arguments
	if len(flag.Args()) > 0 {
		fmt.Fprintf(os.Stderr, "Error: Unknown arguments: %v\n\n", flag.Args())
		flag.PrintDefaults()
		os.Exit(1)
	}

	// Determine mode: GUI or CLI
	if *guiMode {
		// TODO: Launch GUI when implemented
		fmt.Println("GUI mode not yet implemented")
		os.Exit(1)
	}

	// Load config to check for saved server URL
	config, err := LoadConfig()
	if err != nil {
		// Non-fatal, just means no config file exists
		config = &AppConfig{}
	}

	// Determine server URL: CLI flag takes precedence, then config file
	serverURL := *server
	if serverURL == "" && config.ProxyURL != "" {
		serverURL = config.ProxyURL
		fmt.Printf("[*] Using server URL from config: %s\n", serverURL)
	}

	// CLI mode - validate required arguments
	if serverURL == "" {
		fmt.Fprintf(os.Stderr, "Error: server URL required (use -server flag or save to config)\n\n")
		flag.PrintDefaults()
		os.Exit(1)
	}

	// Run CLI mode
	runCLI(serverURL, *username, *node, *vmid, config)
}

func runCLI(serverURL, username, node string, vmid int, config *AppConfig) {
	// Create client
	client := NewClient(serverURL)

	// Check server health
	fmt.Println("[*] Checking server health...")
	if err := client.CheckServerHealth(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("[*] Passed server health check")

	// Save server URL to config on successful health check
	if config.ProxyURL != serverURL {
		config.ProxyURL = serverURL
		if err := SaveConfig(config); err != nil {
			// Non-fatal, just warn
			fmt.Fprintf(os.Stderr, "Warning: failed to save config: %v\n", err)
		}
	}

	// Authenticate
	if err := authenticateUser(client, username); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// Start token refresh loop
	stopRefresh := client.StartTokenRefreshLoop()
	defer close(stopRefresh)

	// If node and vmid specified, connect directly
	if vmid != -1 && node != "" {
		if err := connectToVM(client, node, vmid); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		return
	}

	// Interactive mode: loop through VM selection
	for {
		vms, err := client.GetVMs()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}

		selectedNode, selectedVMID, err := selectVM(vms)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}

		if err := connectToVM(client, selectedNode, selectedVMID); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			// Don't exit, allow user to try another VM
		}
	}
}

func authenticateUser(client *Client, username string) error {
	reader := bufio.NewReader(os.Stdin)

	// Prompt for username if not provided
	if username == "" {
		fmt.Print("[>] Enter username: ")
		usernameInput, _ := reader.ReadString('\n')
		username = strings.TrimSpace(usernameInput)

		if username == "" {
			return fmt.Errorf("username cannot be empty")
		}
	}

	fmt.Printf("[>] Enter OTP for %s: ", username)
	otp, _ := reader.ReadString('\n')
	otp = strings.TrimSpace(otp)

	if err := client.Authenticate(username, otp); err != nil {
		return err
	}

	fmt.Println("[*] Authentication successful")
	return nil
}

func selectVM(vms []VM) (string, int, error) {
	fmt.Println("\nNAME\t\tVMID\tNODE\tTYPE")
	for _, vm := range vms {
		fmt.Printf("%s\t%d\t%s\t%s\n", vm.Name, vm.VMID, vm.Node, vm.Type)
	}
	fmt.Printf("\nOr enter \"quit\" to exit the program.\n\n")

	reader := bufio.NewReader(os.Stdin)
	fmt.Printf("[>] Select VMID: ")
	input, _ := reader.ReadString('\n')
	input = strings.TrimSpace(input)

	if input == "quit" {
		fmt.Println("Exiting...")
		os.Exit(0)
	}

	// Find VM by VMID
	for _, vm := range vms {
		if strconv.Itoa(vm.VMID) == input {
			return vm.Node, vm.VMID, nil
		}
	}

	return "", -1, fmt.Errorf("vm not found for id %s", input)
}

func connectToVM(client *Client, node string, vmid int) error {
	fmt.Printf("[*] Connecting to VM %d on node %s...\n", vmid, node)

	spiceText, err := client.GetSpiceFile(node, vmid)
	if err != nil {
		return err
	}

	fmt.Println("[*] Launching SPICE viewer...")
	if err := client.LaunchSpiceViewer(spiceText); err != nil {
		return err
	}

	fmt.Println("[*] SPICE viewer launched successfully")
	// Give viewer a moment to start before potentially showing menu again
	time.Sleep(1 * time.Second)
	return nil
}
