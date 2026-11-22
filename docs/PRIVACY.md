# Privacy Policy — Network Locator

This policy describes how the TOS 7 application **Network Locator** (`network-locator`) handles information. The application is installed and runs on the user's own TerraMaster NAS. The packager of this TOS wrapper does not operate a cloud account service for the app and does not receive a copy of data created by a local installation.

## Who provides the application

The TOS package is published by the independent publisher **qishiyi** through the public repository [github.com/642671/network-locator](https://github.com/642671/network-locator). This is not a TerraMaster official application. No company legal department or formal postal privacy contact is claimed here. Questions about this policy can be opened as issues on that repository.

## What the application does

Network Locator discovers IPv4 devices on the NAS's current local networks by reading this NAS's own routing and neighbor information, and can match devices by the last four hexadecimal characters of a MAC address. It also lets the NAS administrator save a small number of MAC suffixes and notes inside the app.

## Information the application stores on this NAS

The application may store the following only on the NAS where it is installed, typically under `/usr/local/network-locator/data` and `/usr/local/network-locator/logs`:

- saved MAC suffixes and optional notes entered by the user
- local interface, routing, and neighbor information collected during a scan, for display in the app
- service logs and install diagnostic files used to troubleshoot the service

The application does not require you to create an account with the publisher.

## What is not collected or sent to the publisher

The application does not send scan results, saved devices, notes, or logs to the publisher, to TerraMaster, or to any other third-party analytics or advertising service as part of this packaging. It does not include a crash-reporting or telemetry channel to the publisher.

Scanning uses tools already present on the NAS, such as `ip` and `ping`, to read local network state. Those operations stay on the local network. The application is designed not to change the network configuration of the NAS or of other devices.

## Access on this NAS

The service is exposed to the TOS desktop through a local Unix socket at `/var/api/network-locator.sock`. It is not intended to be published as a LAN TCP port. Anyone who can sign in to TOS and open the application can see the scan results and saved entries stored on that NAS.

## Retention and uninstall

Data remains on the NAS until the user deletes it in the application or uninstalls the application. Uninstalling the package stops the service and removes this application's own configuration, data, logs, Unix socket, systemd unit, and service user under `/usr/local/network-locator`. It does not delete unrelated user files on shared storage volumes.

## Changes

The current policy for a given package version is the copy shipped in that package at `/usr/local/network-locator/docs/PRIVACY.md`, also published at [docs/PRIVACY.md](https://github.com/642671/network-locator/blob/main/docs/PRIVACY.md).
