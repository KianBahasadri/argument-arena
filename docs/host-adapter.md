# Declarative host adapter contract

The owner explicitly left server OS, platform, hostname, and access details blank. Terraform therefore begins at an existing Docker API and makes no host assumptions or remote bootstrap calls. `server_os`, `server_identity`, `docker_host`, `platform`, and `secrets_host_path` are required inputs with blank examples. The bot image is Linux OCI; that does not select the physical host OS.

When those facts are supplied, the operator selects an appropriate declarative host configuration (for example, an existing configuration-management role, a machine configuration module, or a managed container VM definition). Keep its platform-specific implementation in a separately reviewed `infra/host/<selected-adapter>/` directory or in the owner's existing host configuration repository. The application Terraform root consumes its outputs and remains the infrastructure entry point for the bot. No platform adapter is executable yet because selecting an OS/runtime bootstrap would invent deliberately missing inputs.

## Input/output boundary

The adapter accepts the owner's OS/version, server identity, chosen architecture, storage location, existing access/UID mapping, and non-secret references to externally managed secret files. Its declarative outputs feed the following application deployment inputs:

| Adapter output | Terraform input / required property |
| --- | --- |
| Recorded OS and daemon identity | `server_os`, `server_identity` matching Docker `info.Name` |
| Explicit socket or SSH Docker endpoint | `docker_host`, no password/key material |
| Linux OCI runtime architecture | `platform`, either `linux/amd64` or `linux/arm64` |
| Dedicated secret directory in daemon filesystem | `secrets_host_path`, containing externally provisioned `discord-token` |
| Durable Docker local-volume storage | Persistent across Docker/service/host restarts; SQLite WAL and OS-lock support |
| UID/GID mapping and path access | Container UID/GID 10001 can write state and read secrets; secrets are not world-readable |

The adapter declares Docker/runtime installation and service enablement, any Linux VM on a non-Linux host, durable backing storage, host firewall/egress policy, secret-directory metadata, backup-directory metadata, and host-specific mount labels/security policy. Docker API access and SSH host verification use the owner's existing administration mechanism. Secret contents remain externally provisioned runtime inputs, outside Terraform variables/state and this adapter's repository. No cloud provider is selected, and this task does not change the shared Clusterfork controller, accounts, authentication, or infrastructure.

## Adapter acceptance before live installation

The chosen adapter must converge without creating another bot process, survive a reboot with Docker/storage available, pass an independently reviewed endpoint/identity check, and preserve the numeric ownership needed by the image. Run [deployment preflight](deployment.md#preflight-plan-and-install) after provisioning its outputs. Test backups and restoration on the selected filesystem. Record the adapter revision with release records so host recovery can replay the same declarative setup.

These steps await the owner's missing server facts and an operator's live installation window. Offline bot/container/Terraform validation is complete independently of that host configuration choice; no live hosting claim follows from it.
