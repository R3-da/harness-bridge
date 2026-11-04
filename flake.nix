{
  description = "agentuse: switch coding-agent harnesses between subscriptions, OpenCode Go and OpenRouter";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs: rec {
        agentuse = pkgs.callPackage ./nix/package.nix { };
        default = agentuse;
      });

      # The package build runs the test suite.
      checks = forAll (pkgs: {
        agentuse = self.packages.${pkgs.stdenv.hostPlatform.system}.agentuse;
      });

      overlays.default = final: _prev: {
        agentuse = final.callPackage ./nix/package.nix { };
      };

      homeManagerModules.default = import ./nix/hm-module.nix self;

      formatter = forAll (pkgs: pkgs.nixfmt-rfc-style);
    };
}
