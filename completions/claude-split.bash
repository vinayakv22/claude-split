# Native claude-split completion. No API calls or credential reads.
_claude_split_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}" choices="" prefix="" configure=0 entry
    COMPREPLY=()
    local argument
    for argument in "${COMP_WORDS[@]:1}"; do
        [[ "$argument" == -- ]] && break
        [[ "$argument" == --configure-subagent ]] && configure=1
    done
    if [[ "$cur" == --*=* ]]; then
        prev="${cur%%=*}"; prefix="$prev="; cur="${cur#*=}"
    fi
    if (( configure )); then
        case "$prev" in
            --auth) choices="x-api-key bearer none" ;;
            --key-env) choices="SUBAGENT_API_KEY DEEPSEEK_API_KEY CLI_PROXY_API_KEY" ;;
            --key-file)
                while IFS= read -r entry; do COMPREPLY+=("$entry"); done < <(compgen -f -- "$cur")
                compopt -o filenames 2>/dev/null || true
                return ;;
            --model|--base-url) return ;;
            *) choices="--model --base-url --auth --key-file --key-env --api-key-stdin --skip-check --require-check --help" ;;
        esac
    else
        case "$prev" in
            --model) choices="opus sonnet haiku fable" ;;
            --fallback-model) choices="opus sonnet haiku fable" ;;
            --effort) choices="low medium high xhigh max" ;;
            --output-format) choices="text json stream-json" ;;
            --input-format) choices="text stream-json" ;;
            --permission-mode) choices="default acceptEdits plan dontAsk bypassPermissions" ;;
            --system-prompt-snapshot) choices="on off" ;;
            --setting-sources) choices="user project local" ;;
            --settings|--mcp-config|--debug-file|--system-prompt-file|--append-system-prompt-file|--agents)
                while IFS= read -r entry; do COMPREPLY+=("$entry"); done < <(compgen -f -- "$cur")
                compopt -o filenames 2>/dev/null || true
                return ;;
            --add-dir|--plugin-dir)
                while IFS= read -r entry; do COMPREPLY+=("$entry"); done < <(compgen -d -- "$cur")
                compopt -o filenames 2>/dev/null || true
                return ;;
            *) choices="--add-dir --agent --agents --allow-dangerously-skip-permissions --allowed-tools --allowedTools --append-system-prompt --autocompact --ax-screen-reader --background --bare --betas --bg --brief --chrome --cloud --continue --dangerously-skip-permissions --debug --debug-file --desktop --disable-slash-commands --disallowed-tools --disallowedTools --effort --environment --exclude-dynamic-system-prompt-sections --fallback-model --file --fork-session --forward-subagent-text --from-pr --help --ide --include-hook-events --include-partial-messages --input-format --json-schema --max-budget-usd --mcp-config --model --name --no-chrome --no-session-persistence --output-format --permission-mode --permission-prompts --plugin-dir --plugin-url --print --prompt-suggestions --remote-control --remote-control-session-name-prefix --replay-user-messages --restricted --resume --safe-mode --session-id --setting-sources --settings --strict-mcp-config --system-prompt --system-prompt-snapshot --teleport --tmux --tools --verbose --version --worktree --rtk --configure-subagent --proxy-check --proxy-help agents attach auth auto-mode doctor gateway import install logs mcp plugin plugins purge respawn rm setup-token stop kill ultrareview update upgrade" ;;
        esac
    fi
    if (( configure )); then
        local word
        for word in "${COMP_WORDS[@]}"; do
            [[ "$word" == --skip-check ]] && choices="${choices//--require-check/}"
            [[ "$word" == --require-check ]] && choices="${choices//--skip-check/}"
        done
    fi
    while IFS= read -r entry; do COMPREPLY+=("$entry"); done < <(compgen -W "$choices" -- "$cur")
    if [[ -n "$prefix" ]]; then
        local index
        for index in "${!COMPREPLY[@]}"; do COMPREPLY[index]="$prefix${COMPREPLY[index]}"; done
    fi
}
complete -F _claude_split_complete claude-split
