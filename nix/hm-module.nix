self:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.hbridge;
  toml = pkgs.formats.toml { };

  # Config files (Codex auth commands, Claude Code's apiKeyHelper) call back
  # into hbridge. Point them at the profile, not the store path, so they
  # survive upgrades and garbage collection.
  # Harness binaries by store path: with shims.wrap the profile's `claude`,
  # `codex`, ... are the hbridge wrappers, so PATH lookup cannot reach the
  # real ones.
  harnessBinaries = lib.mapAttrs (tool: package: {
    binary = lib.getExe' package (cfg.settings.tools.${tool}.binary or tool);
  }) cfg.harnesses;

  settings = lib.recursiveUpdate {
    settings.self = "${config.home.profileDirectory}/bin/hbridge";
    tools = harnessBinaries;
  } cfg.settings;
  generated = toml.generate "hbridge-catalog.toml" (
    settings
    // lib.optionalAttrs (cfg.catalogFile != null) {
      include = [ cfg.catalogFile ] ++ (cfg.settings.include or [ ]);
    }
  );

  # Shims are generated at build time from the built-in catalog plus
  # `settings` (never the mutable catalogFile, which the build cannot see),
  # and call hbridge by its store path.
  shims = pkgs.runCommand "hbridge-shims" { meta.priority = if cfg.shims.wrap then 4 else 5; } ''
    export HOME="$TMPDIR" HBRIDGE_CATALOG=${toml.generate "hbridge-shim-catalog.toml" settings}
    ${lib.getExe cfg.package} install-shims --dir "$out/bin" \
      --command ${lib.escapeShellArg (lib.getExe cfg.package)} \
      ${lib.optionalString cfg.shims.wrap "--wrap"} \
      ${lib.escapeShellArgs cfg.shims.tools} > /dev/null
  '';
in
{
  options.programs.hbridge = {
    enable = lib.mkEnableOption "hbridge, one catalog for switching coding-agent providers";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "hbridge.packages.\${system}.default";
      description = "The hbridge package.";
    };

    harnesses = lib.mkOption {
      type = lib.types.attrsOf lib.types.package;
      default = { };
      example = lib.literalExpression ''
        {
          claude = pkgs.claude-code;
          codex = pkgs.codex;
        }
      '';
      description = ''
        Harness packages to install and launch, keyed by tool name (`claude`,
        `codex`, `kilo`, `pi`, `hermes`). hbridge runs them by store path,
        which {option}`programs.hbridge.shims.wrap` requires: the wrappers
        take over the profile's `claude`, `codex`, ... entries. The packages'
        other binaries stay on PATH.
      '';
    };

    settings = lib.mkOption {
      inherit (toml) type;
      default = { };
      example = lib.literalExpression ''
        {
          settings.self = "hbridge";
          credentials.opencode-go.sources = [ { file = "/run/secrets/opencode_go_api_key"; } ];
          tools.codex.providers.go.model = "glm-5.3";
        }
      '';
      description = ''
        Catalog entries merged over the built-in defaults, written to
        {file}`~/.config/hbridge/catalog.toml`.
      '';
    };

    catalogFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "\${config.home.homeDirectory}/dotfiles/hbridge/catalog.toml";
      description = ''
        An editable catalog (for example in your dotfiles repository) that the
        generated catalog includes. It is merged after the built-in defaults
        and before {option}`programs.hbridge.settings`, so keep models here
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
          packages; hbridge skips them when it looks up the real binary.
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
    home.packages = [ cfg.package ] ++ lib.attrValues cfg.harnesses ++ lib.optional cfg.shims.enable shims;

    warnings = lib.optional (cfg.shims.wrap && cfg.harnesses == { }) ''
      programs.hbridge.shims.wrap is set without programs.hbridge.harnesses:
      the wrappers shadow the harness binaries in your profile, so hbridge
      can only find them if they are installed outside it.
    '';
    # Always at the default path: surfaces that call `hbridge key` from a
    # desktop app or IDE do not inherit shell variables like HBRIDGE_CATALOG.
    xdg.configFile."hbridge/catalog.toml".source = generated;
  };
}
