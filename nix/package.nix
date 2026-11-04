{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "harness-bridge";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ python3Packages.setuptools ];
  nativeCheckInputs = [ python3Packages.pytestCheckHook ];
  pythonImportsCheck = [ "hbridge" ];

  meta = {
    description = "Switch coding-agent harnesses between subscriptions, OpenCode Go and OpenRouter";
    license = lib.licenses.mit;
    mainProgram = "hbridge";
    platforms = lib.platforms.unix;
  };
}
