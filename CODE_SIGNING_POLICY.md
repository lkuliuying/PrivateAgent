# Code signing policy

Free code signing is provided by [SignPath.io](https://signpath.io/), with a certificate provided by the [SignPath Foundation](https://signpath.org/).

## Scope

Only release artifacts built from the public `lkuliuying/PrivateAgent` repository by the checked-in GitHub Actions workflow may be submitted for signing. The release workflow uses GitHub-hosted Windows runners, uploads the unsigned installer as a GitHub Actions artifact, submits that immutable artifact to SignPath, verifies the returned Authenticode signature, and then regenerates the independent Tauri updater signature over the signed installer.

Third-party binaries are not submitted for signing as PrivateAgent-owned binaries. Dependencies remain subject to their respective open-source licenses.

## Team roles

The project is currently maintained by one owner:

- Committer and reviewer: [@lkuliuying](https://github.com/lkuliuying)
- Signing-request approver: [@lkuliuying](https://github.com/lkuliuying)

Changes from contributors without direct commit access must be reviewed by the maintainer before merging. Every release signing request requires manual approval in SignPath.

## Release controls

- Source and workflow definitions must be present in the public repository.
- Signing builds run only on GitHub-hosted runners.
- The SignPath API token and Tauri updater private key are stored as GitHub Actions secrets and are never committed.
- Release assets are attached only after Authenticode verification succeeds.
- The Tauri updater `.sig` is generated after Authenticode signing because Authenticode changes the installer bytes.
- Release tags and application versions must match.
- The SHA-256 digest and signing status are retained with the release evidence.

## Privacy

PrivateAgent does not transfer information to networked systems unless the user or operator specifically requests or enables it. See the full [privacy policy](PRIVACY.md).

## Incident response

If a signing credential, release workflow, or published artifact is suspected of compromise, signing is paused, affected releases are withdrawn, credentials are rotated, and the incident is documented before signing resumes.
