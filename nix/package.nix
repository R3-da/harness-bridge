{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "agentuse";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ python3Packages.setuptools ];
  nativeCheckInputs = [ python3Packages.pytestCheckHook ];
  pythonImportsCheck = [ "agentuse" ];

  meta = {
    description = "Switch coding-agent harnesses between subscriptions, OpenCode Go and OpenRouter";
    license = lib.licenses.mit;
    mainProgram = "agentuse";
    platforms = lib.platforms.unix;
  };
}
