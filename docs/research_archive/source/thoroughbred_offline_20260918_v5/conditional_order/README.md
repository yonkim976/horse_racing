# Frozen conditional-order experiment

This folder owns one predeclared eight-coefficient sequential order candidate. `protocol_frozen.json` was written before any candidate metrics were computed. A pre-result mathematical review then identified that linear candidate-minus-selected terms cancel from conditional-softmax odds; before fitting, those four terms were replaced by squared gaps and the amendment was recorded in `pre_result_amendment.json`. The first-place distribution is the frozen V2 H3 win model. Second and third place use separately fitted conditional softmax utilities. Coefficients use previous-year Q3 only; previous-year Q4 supplies venue/global C-temperature calibration.

Run `python code/run_conditional_order.py`. The run refuses to overwrite result artifacts. `code/infer.py` exposes reusable complete-card inference and returns `targets_core.JointDistribution`.
