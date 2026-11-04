self:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.agentuse;
  toml = pkgs.formats.toml { };

  # Config files (Codex auth commands, Claude Code's apiKeyHelper) call back
  # into agentuse. Point them at the profile, not the store path, so they
  # survive upgrades and garbage collection.
  settings = lib.recursiveUpdate {
    settings.self = "${config.home.profileDirectory}/bin/agentuse";
  } cfg.settings;
  generated = toml.generate "agentuse-catalog.toml" (
    settings
    // lib.optionalAttrs (cfg.catalogFile != null) {
      include = [ cfg.catalogFile ] ++ (cfg.settings.include or [ ]);
    }
  );

  # Shims are generated at build time from the built-in catalog plus
  # `settings` (never the mutable catalogFile, which the build cannot see),
  # and call agentuse by its store path.
  shims = pkgs.runCommand "agentuse-shims" { meta.priority = if cfg.shims.wrap then 4 else 5; } ''
    export HOME="$TMPDIR" AGENTUSE_CATALOG=${toml.generate "agentuse-shim-catalog.toml" settings}
    ${lib.getExe cfg.package} install-shims --dir "$out/bin" \
      --command ${lib.escapeShellArg (lib.getExe cfg.package)} \
      ${lib.optionalString cfg.shims.wrap "--wrap"} \
      ${lib.escapeShellArgs cfg.shims.tools} > /dev/null
  '';
in
{
  options.programs.agentuse = {
    enable = lib.mkEnableOption "agentuse, one catalog for switching coding-agent providers";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "agentuse.packages.\${system}.default";
      description = "The agentuse package.";
    };

    settings = lib.mkOption {
      inherit (toml) type;
      default = { };
      example = lib.literalExpression ''
        {
          settings.self = "agentuse";
          credentials.opencode-go.sources = [ { file = "/run/secrets/opencode_go_api_key"; } ];
          tools.codex.providers.go.model = "glm-5.3";
        }
      '';
      description = ''
        Catalog entries merged over the built-in defaults, written to
        {file}`~/.config/agentuse/catalog.toml`.
      '';
    };

    catalogFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "\${config.home.homeDirectory}/dotfiles/agentuse/catalog.toml";
      description = ''
        An editable catalog (for example in your dotfiles repository) that the
        generated catalog includes. It is merged after the built-in defaults
        and before {option}`programs.agentuse.settings`, so keep models here
        and machine-specific values such as secret paths in `settings`.
      '';
    };

    shims = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Install ccuse, cxuse, kuse, piuse, huse and the <tool>-<provider> one-shots.";
      };
      wrap = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Also install `claude`, `codex`, ... wrappers that inject provider
          keys into plain launches. They take priority over the harness
          packages; agentuse skips them when it looks up the real binary.
        '';
      };
      tools = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        example = [ "claude" "codex" ];
        description = "Limit the shims to these harnesses (default: all).";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ] ++ lib.optional cfg.shims.enable shims;
    # Always at the default path: surfaces that call `agentuse key` from a
    # desktop app or IDE do not inherit shell variables like AGENTUSE_CATALOG.
    xdg.configFile."agentuse/catalog.toml".source = generated;
  };
}
