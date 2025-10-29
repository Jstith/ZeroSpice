# Install

Installing the ZeroSpice Proxy server involves three steps:
1. Install ZeroTier and join the server's host to ZeroTier.
2. Download dependencies, configure variables, and run the web server.
3. Generate user secrets for TOTP authentication.

**Installing the Proxy Server:**

- Steps 1 and 2 can be achieved by running the `install.sh` script with `sudo ./install.sh`.
- Step 3 can be achieved by running `python3 src/setup_topt.py <username>` and following the instructions in the program.
