"""AI job-application generator for the Job hunt "Apply" flow.

Built with two agent patterns:
  - orchestrator-workers: `orchestrator.build_plan` analyses the job + the user's
    brain and produces an application plan (which uploaded documents to attach,
    whether a cover letter is needed, key points/tone), then delegates the
    cover-letter drafting to a worker (`workers.draft_cover_letter`).
  - evaluator-optimizer: `evaluator.optimize_loop` has an evaluator LLM critique
    the draft against the job requirements and re-draft in a short loop. User
    feedback re-enters this same loop.

The result is one merged PDF: the typeset cover letter followed by the user's
original CV/certificate files (`assembler.assemble_pdf`). `service.generate_application`
is the background entrypoint that wires it all together and persists the result.
"""
