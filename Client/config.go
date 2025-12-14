package main

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// AppConfig stores persistent application settings
type AppConfig struct {
	ProxyURL string `json:"proxy_url"`
}

// getConfigPath returns the path to the config file
func getConfigPath() (string, error) {
	// Use current directory for config file (matching Python implementation)
	exePath, err := os.Executable()
	if err != nil {
		return "", err
	}
	configDir := filepath.Dir(exePath)

	// If running with "go run", use current working directory
	if filepath.Base(configDir) == "exe" || filepath.Base(configDir) == "T" {
		configDir, _ = os.Getwd()
	}

	return filepath.Join(configDir, "config.json"), nil
}

// LoadConfig loads the application configuration from disk
func LoadConfig() (*AppConfig, error) {
	configPath, err := getConfigPath()
	if err != nil {
		return &AppConfig{}, err
	}

	// If config doesn't exist, return empty config
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return &AppConfig{}, nil
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		return &AppConfig{}, err
	}

	var config AppConfig
	if err := json.Unmarshal(data, &config); err != nil {
		// If config is invalid, return empty config
		return &AppConfig{}, nil
	}

	return &config, nil
}

// SaveConfig saves the application configuration to disk
func SaveConfig(config *AppConfig) error {
	configPath, err := getConfigPath()
	if err != nil {
		return err
	}

	data, err := json.MarshalIndent(config, "", "    ")
	if err != nil {
		return err
	}

	return os.WriteFile(configPath, data, 0644)
}
