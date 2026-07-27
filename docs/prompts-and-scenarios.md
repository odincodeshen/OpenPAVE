# Prompt Presets and Demo Scenarios

OpenPAVE stores prompt presets and demo scenarios as versioned repository assets so validated baseline runs can be repeated and compared.

## Prompt Presets

Prompt presets live in:

```text
prompts/
```

Each prompt preset describes:

- stable prompt text
- task type
- expected output contract
- safety policy
- sensor assumptions when relevant

Current prompt presets:

- `prompts/intent-stop-trot.json`
- `prompts/robot-commander-gesture.json`
- `prompts/scene-understanding.json`
- `prompts/object-recognition.json`
- `prompts/navigation-suggestion.json`

## Demo Scenarios

Demo scenarios live in:

```text
scenarios/
```

Each scenario describes:

- prompt reference
- expected intents or expected observation behavior
- safety constraints
- robot/sensor endpoint assumptions
- inference node assumptions
- adapter assumptions
- runtime profile
- success criteria

Current scenarios:

- `scenarios/mock-intent-stop-trot.json`
- `scenarios/puppypi-gesture-stop-trot.json`
- `scenarios/scene-understanding-camera.json`
- `scenarios/object-recognition-camera.json`
- `scenarios/navigation-suggestion-camera.json`

## Add a Prompt

1. Create a new JSON file under `prompts/`.
2. Use a stable `id` and explicit `version`.
3. Define the output contract clearly.
4. Mark whether the prompt can produce robot intent.
5. Use a safe fallback for any physical robot control prompt.

## Add a Scenario

1. Create a new JSON file under `scenarios/`.
2. Reference an existing prompt with `prompt_ref`.
3. Define robot/sensor endpoint assumptions explicitly.
4. Define inference node assumptions explicitly.
5. Define adapter assumptions explicitly.
6. Add success criteria that can later become benchmark checks.

Run validation after adding or editing assets:

```bash
python3 -B -m unittest discover
```

## Physical Robot Safety

Scenarios that can produce robot motion must declare safety constraints. For the current PuppyPi flow, `STOP` is the safe fallback and `TROT` should require runtime confirmation.
