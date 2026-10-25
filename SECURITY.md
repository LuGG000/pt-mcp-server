# Security Policies and Procedures

This document outlines security procedures and general policies for the
`pt-mcp` project.

- [Reporting a Bug](#reporting-a-bug)
- [Security Model](#security-model)
- [Disclosure Policy](#disclosure-policy)
- [Comments on this Policy](#comments-on-this-policy)

## Reporting a Bug

The `pt-mcp` team and community take all security bugs in `pt-mcp` seriously.
Thank you for improving the security of `pt-mcp`. We appreciate your efforts and
responsible disclosure and will make every effort to acknowledge your contributions.

Report security bugs by emailing `kiskande@cisco.com`.

The lead maintainer will acknowledge your email as soon as possible. Typically, this will
be within 48 hours, but circumstances may require it take longer. After the initial reply
to your report, the author will attempt to resolve the issue and notify you of the remediation.

## Security Model

- **ExApp key.** `pt-mcp setup` generates a random key per install and stores it in the user's config
  folder (`pt-mcp.env`, readable only by the user on macOS/Linux). Anyone who has the key and can reach
  Packet Tracer's IPC port can act with the ExApp's privileges, so keep the file private and IPC bound to
  localhost (Packet Tracer's "Allow Remote Applications" off).
- **PTMP is not encrypted.** Only use remote Packet Tracer connections (`PT_HOST`) on trusted networks.
- **Privileges.** The ExApp does not request `ACTIVITY_WIZARD` (activity answers, scores, password hashes)
  or `MULTIUSER`.
- **Crash protection.** Only verified IPC methods are sent by default; the raw `call_ipc_api` tool is opt-in.
- **HTTP transport** has no authentication of its own. Bind it to localhost, or put it behind an
  authenticating proxy.

## Disclosure Policy

When the maintainer receives a security bug report, they will coordinate the fix and release process,
involving the following steps:

- Confirm the problem and determine the affected versions.
- Audit code to find any potential similar problems.
- Prepare fixes for all releases still under maintenance. These fixes will be
  released as quickly as possible.

## Comments on this Policy

If you have suggestions on how this process could be improved please submit a
pull request.
