package main

import (
"fmt"
"flag"
"os"
"net/http"
"strings"
)

type Config struct {
	Server		string
	Username 	string
	OTP			int
	Node		string
	VMID		int
}

func main() {

	config, err := parseInput()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		fmt.Fprintf(os.Stderr, "\nUsage:\n")
		flag.PrintDefaults()
		os.Exit(1)
	}

	fmt.Println("[+] Arguments passed validation check!")

	err = doSomething(config)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

func parseInput() (*Config, error) {
	server := flag.String("server", "", "Domain or IP of the ZeroSpice Server")
	username := flag.String("username", "", "The username used to authenticate to the server")
	otp := flag.Int("otp", -1, "The one time pin for the login session")
	node := flag.String("node", "", "The Proxmox node to access")
	vmid := flag.Int("vmid", -1, "The VMID to access")

	flag.Parse()

	var argErrors []string

	if *server == "" {
		argErrors = append(argErrors, "server is required")
	}
	if *username == "" {
		argErrors = append(argErrors, "username is required")
	}
	if *otp == -1 {
		argErrors = append(argErrors, "otp is required")
	}
	if *node == "" {
		argErrors = append(argErrors, "node is required")
	}
	if *vmid == -1 {
		argErrors = append(argErrors, "vmid is required")
	}
	if len(flag.Args()) > 0 {
		argErrors = append(argErrors, fmt.Sprintf("Unknown arguments: %v", flag.Args()))
	}

	if len(argErrors) > 0 {
		return nil, fmt.Errorf("validation failed: %s", strings.Join(argErrors, ":"))
	}

	return &Config{
		Server:		*server,
		Username:	*username,
		OTP:		*otp,
		Node:		*node,
		VMID:		*vmid,
	}, nil
}

func doSomething(config *Config) error {
	fmt.Printf("[+] Doing something...\n")
	fmt.Printf("Connecting to %s as %s\n", config.Server, config.Username)
	url := config.Server + "/health"
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("failed to connect to %s: %w", url, err)
	}
	defer resp.Body.Close()
	fmt.Printf("Status: %s (code: %d)\n", resp.Status, resp.StatusCode)
	return nil
}
