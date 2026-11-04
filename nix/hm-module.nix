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
  generated = toml.generate "agentuse-catalog.toml" cfg.settings;

  # Shims are generated at build time from the built-in catalog plus
  # `settings`, so they call agentuse by its store path.
  shims = pkgs.runCommand "agentuse-shims" { meta.priority = if cfg.shims.wrap then 4 else 5; } ''
    export HOME="$TMPDIR" AGENTUSE_CATALOG=${generated}
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
        {file}`~/.config/agentuse/catalog.toml`. Ignored when
        {option}`programs.agentuse.catalogFile` is set.
      '';
    };

    catalogFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "\${config.home.homeDirectory}/dotfiles/agentuse/catalog.toml";
      description = ''
        Use an existing, editable catalog file instead of generating one from
        {option}`programs.agentuse.settings`. Exported as `AGENTUSE_CATALOG`.
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
    xdg.configFile."agentuse/catalog.toml" = lib.mkIf (cfg.catalogFile == null && cfg.settings != { }) {
      source = generated;
    };
    home.sessionVariables = lib.mkIf (cfg.catalogFile != null) {
      AGENTUSE_CATALOG = cfg.catalogFile;
    };
  };
}
