# Native claude-split completions. No API calls or credential reads.
complete -c claude-split -e
complete -c claude-split -f
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l configure-subagent -d 'Configure the subagent provider'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l proxy-check -d 'Show proxy status'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l proxy-help -d 'Show split launcher help'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l add-dir -d 'Additional directories to allow tool' -r -a '(__fish_complete_directories)'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l agent -d 'Agent for the current session. Overrides' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l agents -d 'JSON object defining custom agents, or' -r -F
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l allow-dangerously-skip-permissions -d 'Enable bypassing all permission checks'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l allowed-tools -d 'Allowed tools' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l allowedTools -d 'Allowedtools' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l append-system-prompt -d 'Append a system prompt to the default' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l autocompact -d 'Auto-compact window size (auto, or' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l ax-screen-reader -d 'Render screen-reader friendly output'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l background -d 'Start the session in the background and'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l bare -d 'Minimal mode: skip hooks (those defined'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l betas -d 'Beta headers to include in API requests' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l bg -d 'Start the session in the background and'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l brief -d 'Enable SendUserMessage tool for'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l chrome -d 'Enable Claude in Chrome integration'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l cloud -d 'Create a cloud session with the given'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l continue -d 'Continue the most recent conversation in'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l dangerously-skip-permissions -d 'Bypass all permission checks.'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l debug -d 'Enable debug mode with optional category'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l debug-file -d 'Write debug logs to a specific file path' -r -F
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l desktop -d 'Open in the Claude Desktop app instead'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l disable-slash-commands -d 'Disable all skills and commands'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l disallowed-tools -d 'Disallowed tools' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l disallowedTools -d 'Disallowedtools' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l effort -d 'Effort level for the current session' -r -a 'low medium high xhigh max'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l environment -d 'Create a new cloud session that runs on' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l exclude-dynamic-system-prompt-sections -d 'Exclude dynamic system prompt sections'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l fallback-model -d 'Enable automatic fallback to specified' -r -a 'opus sonnet haiku fable'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l file -d 'File resources to download at startup.' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l fork-session -d 'When resuming, create a new session ID'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l forward-subagent-text -d 'Forward subagent text and thinking'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l from-pr -d 'Resume a session linked to a PR by PR'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l help -d 'Display help for command'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l ide -d 'Automatically connect to IDE on startup'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l include-hook-events -d 'Include all hook lifecycle events in the'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l include-partial-messages -d 'Include partial message chunks as they'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l input-format -d 'Input format (only works with --print):' -r -a 'text stream-json'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l json-schema -d 'JSON Schema for structured output' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l max-budget-usd -d 'Maximum dollar amount to spend on API' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l mcp-config -d 'Load MCP servers from JSON files or' -r -F
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l model -d 'Model for the current session. Provide' -r -a 'opus sonnet haiku fable'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l name -d 'Set a display name for this session' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l no-chrome -d 'Disable Claude in Chrome integration'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l no-session-persistence -d 'Disable session persistence - sessions'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l output-format -d 'Output format (only works with --print):' -r -a 'text json stream-json'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l permission-mode -d 'Permission mode to use for the session' -r -a 'default acceptEdits plan dontAsk bypassPermissions'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l permission-prompts -d 'Who answers permission prompts with' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l plugin-dir -d 'Load a plugin from a directory or .zip' -r -a '(__fish_complete_directories)'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l plugin-url -d 'Fetch a plugin .zip from a URL for this' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l print -d 'Print response and exit (useful for'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l prompt-suggestions -d 'Enable prompt suggestions. In print/SDK'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l remote-control -d 'Start an interactive session with Remote'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l remote-control-session-name-prefix -d 'Remote control session name prefix' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l replay-user-messages -d 'Re-emit user messages from stdin back on'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l restricted -d 'Restricted mode: removes the built-in'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l resume -d 'Resume a conversation by session ID or'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l safe-mode -d 'Start with all customizations'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l session-id -d 'Use a specific session ID for the' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l setting-sources -d 'Comma-separated list of setting sources' -r -a 'user project local'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l settings -d 'Path to a settings JSON file or a JSON' -r -F
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l strict-mcp-config -d 'Only use MCP servers from --mcp-config,'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l system-prompt -d 'System prompt to use for the session' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l system-prompt-snapshot -d 'Record the system prompt once per' -r -a 'on off'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l teleport -d 'Resume a teleport session, optionally'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l tmux -d 'Create a tmux session for the worktree'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l tools -d 'Specify the list of available tools from' -r
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l verbose -d 'Override verbose mode setting from'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l version -d 'Output the version number'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l worktree -d 'Create a new git worktree for this'
complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent; and __fish_use_subcommand' -a 'agents attach auth auto-mode doctor gateway import install logs mcp plugin plugins purge respawn rm setup-token stop kill ultrareview update upgrade' -d 'Claude Code command'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l provider -d 'Provider preset' -r -a 'anthropic deepseek local minimax moonshot openrouter zai'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l model -d 'Upstream subagent model ID' -r
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l base-url -d 'Anthropic-compatible endpoint' -r
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l auth -d 'Provider authentication' -r -a 'x-api-key bearer none'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l key-file -d 'Private API key file' -r -F
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l key-env -d 'API key entry in dotenv file' -r -a 'SUBAGENT_API_KEY DEEPSEEK_API_KEY CLI_PROXY_API_KEY'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l api-key-stdin -d 'Read API key from stdin'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l api-key-env -d 'Read API key from environment variable' -r
complete -c claude-split -n '__fish_seen_argument -l configure-subagent' -l help -d 'Show configuration help'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent; and not __fish_seen_argument -l require-check' -l skip-check -d 'Skip tool test; still verify authentication/model'
complete -c claude-split -n '__fish_seen_argument -l configure-subagent; and not __fish_seen_argument -l skip-check' -l require-check -d 'Require authentication, model and tool tests to pass'

complete -c claude-split -n 'not __fish_seen_argument -l configure-subagent' -l rtk -d 'Compress main and subagent requests through local RTK'
