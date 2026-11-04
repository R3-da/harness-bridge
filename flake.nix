{
  description = "harness-bridge (hbridge): switch coding-agent harnesses between subscriptions, OpenCode Go and OpenRouter";

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
        harness-bridge = pkgs.callPackage ./nix/package.nix { };
        default = harness-bridge;
      });

      # The package build runs the test suite.
      checks = forAll (pkgs: {
        harness-bridge = self.packages.${pkgs.stdenv.hostPlatform.system}.harness-bridge;
      });

      overlays.default = final: _prev: {
        harness-bridge = final.callPackage ./nix/package.nix { };
      };

      homeManagerModules.default = import ./nix/hm-module.nix self;

      formatter = forAll (pkgs: pkgs.nixfmt);
    };
}
