# Privacy policy

PrivateAgent is local-first software. It does not transfer information to other networked systems unless the user, installer, or operator specifically requests or enables that behavior.

## Local data

Conversations, memories, projects, knowledge-base content, vector indexes, settings, logs, credentials, and backups are stored on systems selected by the user. The application does not provide the maintainers with automatic access to this data.

## Network access

PrivateAgent can make network requests only for features selected or configured by the user, including:

- local or user-configured Ollama endpoints;
- optional OpenAI-compatible or Anthropic model providers;
- explicitly configured MCP servers and integrations;
- GitHub Releases used to check for and download application updates.

Before enabling a remote provider or integration, review the provider's own privacy terms. Relevant upstream policies include [OpenAI's privacy policy](https://openai.com/policies/privacy-policy/), [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy), [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement), and the policy of any user-configured endpoint.

## Diagnostics

Diagnostic exports are created only on user request. The project attempts to redact secrets and excludes database passwords, API keys, full chat contents, document bodies, and sensitive memories by default. Users should still review an export before sharing it.

## Updates

Update checks contact `github.com` to retrieve the public `latest.json` manifest and release assets. The updater verifies the Tauri updater signature before installing an update.

## Contact

Privacy questions and vulnerability reports can be filed through the repository's GitHub issue or security-reporting facilities: <https://github.com/lkuliuying/PrivateAgent>.
