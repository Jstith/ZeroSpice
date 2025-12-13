# Go Branch!!

I am working on transitioning the front end of ZeroSpice into Go, and transitioning the mesh net infrastructure to tailscale. Currently, I have ported the following features:
- CLI authentication
- CLI interactive session spawning
- CLI SPICE file handling

I am still working on:
- Building the GUI in Go
- Updating integrating tailscale to the Go application
- Updating the server to be compatable with tailscale

# ZeroSpice: Secure Remote Access to Proxmox VMs

ZeroSpice is a python-based toolkit that enables secure remote access to Proxmox VMs using the SPICE protocol in a private environment. Leveraging two open-source technologies: ZeroTier and Spice, ZeroSpice delivers a security-focused yet robust way to use virtual machines from anywhere on the internet, prioritizing accessability and least privilege to build a modern, secure access environment.

![ZeroSpice Demo](docs/zerospice-demo.gif)

![Python 3 compatible](https://img.shields.io/badge/python-3.x-blue.svg)
![PyPI version](https://img.shields.io/pypi/v/bloodhound.svg)
![License: MIT](https://img.shields.io/pypi/l/bloodhound.svg)

---

## Table on Contents

1. [Overview](#overview)
2. [Install](#install)
3. [Problem Statement](#problem-statement)
4. [Architecture & Design](#architecture--design)

## Overview

ZeroSpice is a client-server toolkit that leverages two open source technologies: the [ZeroTier](https://www.zerotier.com/) networking protocol and the [SPICE](https://www.spice-space.org/) remote access protocol to deliver robust remote access to Proxmodx virtual machines from anywhere. Using this toolkit, you can access virtual machines hosted on a private Proxmox VE without exposing the Proxmox server, port forwarding through a public endpoint, or exposing Proxmox credentials and API keys. All connections benefit from strong end-to-end encryption while maintaining the speed/capability of the SPICE protocol. The client and server are written in python, with a GUI created using Tom Schimansky's [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).

## Install

Detailed instructions to install ZeroSpice can be found in [INSTALL.md](./INSTALL.md).

The installation instructions cover all necessary components of setting up ZeroSpice, including:
- Setting up a Proxmox API token
- Setting up a ZeroTier network
- Setting up the ZeroSpice server
- Creating user accounts & secrets on the ZeroSpice server
- Installing the ZeroSpice client

## Problem Statement

Modern remote access protocols like SPICE (2009) offer significant advantages over legacy solutions like RDP and VNC (1998), including lower latency, 3D graphics acceleration, native USB passthrough, and bi-directional audio. However, SPICE's requirement for direct hypervisor communication creates a challenge: how do you safely expose Proxmox virtual machines for SPICE remote access without compromising security?

Traditional approaches fall short of solving this:
- **Legacy remote access solutions** rely on guest OS protocols (RDP, VNC) rather than hypervisor-level communication. Open-source tools like [Apache Guacamole](https://guacamole.apache.org/), [noVNC](https://novnc.com/info.html), and [Kasm Workspaces](https://kasm.com/workspaces) provide web-based access to VMs, while tools like [Remmina](https://remmina.org/) and [TigerVNC](https://tigervnc.org/) offer native desktop applications. Commercial tools like [Citrix Virtual Apps](https://www.citrix.com/platform/citrix-app-and-desktop-virtualization/), [VMware Horizon View](https://en.wikipedia.org/wiki/Omnissa_Horizon), and [Windows Remote Desktop Services](https://learn.microsoft.com/en-us/windows-server/remote/remote-desktop-services/remote-desktop-services-overview) provide similar enterprise-grade services. **Critically, none of these solutions support SPICE** - they all communicate with the guest operating system rather than the hypervisor, sacrificing SPICE's performance advantages and robust features.
- **Commercial hypervisor solutions**, including [VMware ESXi](https://www.vmware.com/products/cloud-infrastructure/vsphere) and [Microsoft Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/overview), are locked into closed-source, proprietary software ecosystems and walled behind prohibitive licensing costs.
- **"Home Lab Remedy" solutions**, including direct exposure of Proxmox, port forwarding with [Cloudflare tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/), etc., present security risks I was not comfortable with in my homelab, including public access to the Proxmox Virtual Environment API and the storage of Proxmox credentials and/or API keys outside of my internal environment.

**The ZeroSpice project solves this problem** by combining SPICE's performance with ZeroTier's encrypted mesh networking and a least-privilege proxy server, enabling secure remote access to Proxmox VMs without exposing the hypervisor or letting access credentials leave the internal environment.

**Why This Matters**
The ZeroSpice project shows that industry-standard secure remote access does not require enterprise budgets, and that leveraging open-source tools and protocols enables secure remote access to virtual environments without sacrificing the benefits of SPICE or paying prohibitive licensing costs.

## Architecture & Design

At its Core, ZeroSpice consists of a Proxmox host, an HTTP server, a ZeroTier network, and at least one client device.
- **Proxmox Host**: Hosts virtual machines accessed via ZeroSpice. ZeroSpice does not run any code on Proxmox
- **ZeroSpice Server**: Uses a Proxmox API key to control SPICE sessions, authenticates clients and routes sessions to them via ZeroTier
- **ZeroSpice Client**: Authenticates to the ZeroSpice server via ZeroTier routing, receives SPICE connection from ZeroSpice server for interactive use.
- **ZeroTier Network**: Routes traffic between the Client(s) and server using end-to-end encrypted, UDP-based mesh net routing, allowing for complex NAT traversal to route between private and public networks.

The client(s) and proxy server are joined with ZeroTier's mesh net routing protocol, and client(s) communicate with the proxy exclusively through ZeroTier. Utilizing an HTTP API, client(s) make requests to the proxmox server through the proxy server. The Proxmox API key used to authorize actions on Proxmox is stored on the proxy server. This way, client(s) only know the ZeroTier IP of the proxy server, and only broker access to VMs through HTTP API requests.

<picture>
    <source media="prefers-color-scheme: dark)" srcset="./docs/ZeroSpice_Sequence_Diagram_Dark.svg">
    <source media="preferse-color-scheme: light)" srcset="./dosc/ZeroSpice_Sequence_Diagram_Light.svg">
    <img alt="ZeroSpice Sequence Diagram" src="./docs/ZeroSpice_Sequence_Diagram_Light.svg">
</picture>

### Why ZeroTier?

ZeroTier's mesh networking solves the fundamental challenge of secure remote access.
- **Peer-to-peer routing:** Devices using ZeroTier communicate directly without port forwarding or reverse proxies.
- **NAT traversal:** ZeroTier has robust route finding and NAT translation making communication to and from almost anywhere on the internet possible
- **End-to-end encryption:** All ZeroTier traffic comes across the wire as AES-256 encrypted, stateless UDP traffic.
- Open source: Unlike most commercial alternatives ZeroTier is fully customizable and has a solid SDK for deeper integrations.
I'd like to build a future iteration of this toolkit that integrates ZeroTier directly into the scripts so you don't need to install the heavier zerotier-one service to the hosts. This level of granularity is something commercial mesh routing services do not offer.

### Why a Proxy Server?

A proxy server solves the credential exposure problem. Without it, any host using SPICE would need to save either credentials or Proxmox API key, creating various security risks by doing so.
- **Credential theft:** In the event a client running ZeroSpice is compromised, neither the Proxmox host or credentials / API keys for the Proxmox host are at direct risk.
- **Over-privileged access:** Proxmox API keys have a limited granularity of permissions. Almost inevitably, a Proxmox API key will be able to do slightly more than the exact thing you want it to do. By putting that API key behind a proxy, ZeroSpice can restrict user functions to exactly what the proxy offers clients and nothing more.
- **User authentication:** Since Proxmox secrets are *not* used to authenticate authorized clients, *something* has to. The proxy server enables user authentication (currently using TOTP) to prevent unauthorized access to the API functions, even within the ZeroTier environment.
- **Distributed Secrets:** A tertiary benefit to the proxy server is that multiple clients using ZeroSpice will not have to deal with the headaches of shared secrets. The proxy server is able to centrally manage all aspects of authorization (aside from joining the machines to ZeroTier... for now).
The proxy server acts as a credential vault and authorization gateway, exposing a limited number of API functions for VM access to authorized clients.

### Security Model

ZeroSpice aims to provide defense in depth throughout all stages of the remote access process.
1. **Network Layer:** Encrypted peer-to-peer traffic and restricted access to proxmox for clients
2. **Application Layer:** TOTP-based Authentication to access Proxy API functions, no client access to Proxmox API
3. **Secrets Isolation:** Proxmox secrets never leave the proxy server

This model protects against several flaws / weaknesses in other remote access implementations, including:
- Exposing the Proxmox API to the internet
- Credential theft from compromised client devices
- Unauthorized access from compromised client devices

Notably, *session hijacking* is still a legitimate attack vector against ZeroSpice. This is an inherent risk to all remote access protocols. If the JWT for the Proxy API and a SPICE configuration file are stolen in real time, they could be used to take over the user session. I am planning to at least partially mitigate this in future versions of the tool by making the port forwarder more picky about who and when it forwards traffic for.
