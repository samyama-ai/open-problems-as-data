# Hand-check of LLM status verdicts (solves / refutes)

Judge: one LLM-assisted reviewer (Claude), not independent domain experts. Inputs: problem statement and status rationale from the graph, work title, year and OpenAlex abstract, the verdict's quote. Full texts were not read. Graph and statuses were not changed.

## Totals

- AI solves: 0 correct / 3 partly / 0 wrong / 0 cannot tell (n=3)
- AI refutes: 8 correct / 23 partly / 1 wrong / 0 cannot tell (n=32)
- DBMS solves: 1 correct / 3 partly / 0 wrong / 0 cannot tell (n=4)
- DBMS refutes: 0 correct / 1 partly / 1 wrong / 0 cannot tell (n=2)
- All 41: 9 correct, 30 partly, 2 wrong, 0 cannot tell.
- No 'refutes' verdict (0 of 34) disproves an open problem. The pipeline's 'refutes' means 'contradicts a claim on the problem page'; read that way, 8 of 32 AI refutes are correct.
- Only 1 of 7 'solves' closes the question the statement calls central (DBMS query determinacy, Gogacz and Marcinkowski 2015). The other 6 solve a sub-case.
- Mean LLM confidence: AI correct 0.73, partly 0.6, wrong 0.4. Correct items carry higher mean confidence; n is small (35), so this is not a usable threshold (observed, not tested).

## Definitions

- **correct**: the paper does what the verdict says to a claim or question in the problem statement.
- **partly**: the paper bears on the problem but advances it, solves a sub-case, or contradicts an adjacent or rival claim.
- **wrong**: the paper does not do what the verdict says.
- **cannot tell**: not enough information (none used).

## Failure patterns (41 verdicts)

- 9: current methods fail, read as refuting an open 'can it be done' problem.
- 6: solves a sub-case only.
- 6: evidence from an adjacent or restricted setting.
- 5: answers or advances a sub-question, labelled refutes.
- 4: refutes a rival explanation or prior result, not the problem.
- 1: source paper of the phenomenon labelled refutes.
- 1: performance comparison read as refutation.
- 0: wrong or mismatched abstract. All 41 abstracts match their work titles. The known bad abstract (W3001279689, Scaling Laws) carries no solves/refutes verdict. The status rationale for `04-alignment/corrigibility-with-competent-agency` notes a mismatched abstract on another linked paper (paper 0, verdict not solves/refutes).
- Problem statements: AI statements are one paragraph (309-1,060 chars) and most state a question, not a claim, so 'refutes' often has no explicit target. 5 of the 8 correct AI refutes are on problems whose statement names the claim under examination (ICL as gradient descent, steering reliability x2, perplexity sufficiency, distillation privacy).

## AI (http://localhost:18089)

| # | Problem | Work | Verdict | Judgement | Reason |
|---|---|---|---|---|---|
| 1 | `14-long-context/packed-sequence-cross-document-attention` | W4303647954 Efficient Sequence Packing without Cross-contam… (2021) | solves | partly | Packing with a block-diagonal mask removes contamination at BERT scale; the effect of contamination on LLM pretraining is not measured. |
| 2 | `23-privacy-memorization/hidden-state-privacy-accounting` | W7133221422 Privacy of Noisy Stochastic Gradient Descent: M… (2022) | solves | partly | Tight privacy bound for noisy SGD, but only for smooth convex losses on a bounded domain; the nonconvex case in the title stays open. |
| 3 | `24-multimodal/modality-gap-contrastive-embeddings` | W4399197904 It's Not a Modality Gap: Characterizing and Add… (2024) | solves | partly | Gives one explanation (the contrastive loss creates the gap) and a loss fix; a single self-claim among competing explanations. |
| 4 | `01-tokenization/intrinsic-tokenizer-metrics` | W7131854743 Two Counterexamples to Tokenization and the Noi… (2024) | refutes | partly | Counterexamples break one intrinsic metric (Renyi efficiency); the question whether any intrinsic statistic predicts outcomes stays open. |
| 5 | `02-attention/attention-as-faithful-explanation` | W2973291083 Learning to Deceive with Attention-Based Explan… (2020) | refutes | correct | Models can put low attention on tokens they still rely on, so attention weight need not track causal contribution. |
| 6 | `02-attention/icl-implicit-gradient-descent` | W4387636023 Do pretrained Transformers Learn In-Context by… (2023) | refutes | correct | Statement names the claim; on LLaMa-7B, ICL and GD differ in order sensitivity and output shift. Empirical, pretrained LLMs only. |
| 7 | `03-training-dynamics/adam-vs-sgd-transformers` | W4367553283 Noise Is Not the Main Factor Behind the Gap Bet… (2023) | refutes | partly | Refutes one candidate explanation (heavy-tailed noise) of the Adam-SGD gap; the gap itself is confirmed. |
| 8 | `04-alignment/activation-steering-reliability` | W4404261821 Towards Reliable Evaluation of Behavior Steerin… (2024) | refutes | partly | Proposes an evaluation protocol; 'some interventions less effective than reported' is weak counter-evidence. |
| 9 | `04-alignment/activation-steering-reliability` | W4404986049 Analyzing the Generalization and Reliability of… (2024) | refutes | correct | Statement claims steering is reliable and generalises; paper finds high per-input variance and weak OOD generalisation. |
| 10 | `04-alignment/activation-steering-reliability` | W4406961517 AxBench: Steering LLMs? Even Simple Baselines O… (2025) | refutes | correct | Statement claims steering beats prompting as a control surface; AxBench finds prompting beats all steering methods (Gemma-2 2B/9B). |
| 11 | `04-alignment/corrigibility-with-competent-agency` | W4399802822 The shutdown problem: an AI engineering puzzle… (2024) | refutes | partly | Theorems show agents meeting stated conditions resist or cause shutdown; an impossibility under assumptions, which the author says guides solutions. |
| 12 | `04-alignment/debate-truth-amplification` | W4285106084 Single-Turn Debate Does Not Help Humans Answer… (2022) | refutes | partly | Single-turn, non-interactive arguments did not help humans; multi-turn debate with a judge is not tested. |
| 13 | `06-data-pipeline/influence-function-stability-at-scale` | W7133212451 If Influence Functions Are the Answer, Then Wha… (2022) | refutes | partly | Influence estimates track the PBRF, not leave-one-out retraining; this answers the 'what do they estimate' sub-question rather than refuting it. No scale or stability result. |
| 14 | `07-embeddings/cross-lingual-alignment-no-parallel-data` | W2798886742 On the Limitations of Unsupervised Bilingual Di… (2018) | refutes | partly | Unsupervised dictionary induction fails on some languages and under domain mismatch; shows limits of current methods, not impossibility. |
| 15 | `08-loss-and-heads/label-smoothing-distillation-interference` | W3123639697 Is Label Smoothing Truly Incompatible with Know… (2021) | refutes | partly | Argues the LS-KD incompatibility view is one-sided but also confirms it holds in some cases; characterises 'when', which is the problem's ask. |
| 16 | `10-scaling-laws/chinchilla-coefficient-reproducibility` | W4394907038 Chinchilla Scaling: A replication attempt (2024) | refutes | partly | Refutes Hoffmann et al.'s third-method fit, but the rederived law agrees with methods 1-2 (about 20 tokens/parameter). |
| 17 | `12-quantization-compression/calibration-set-sensitivity` | W4402671893 On the Impact of Calibration Data in Post-train… (2024) | refutes | partly | Shows calibration data changes downstream accuracy, contradicting prior robustness claims; this answers the empirical question rather than refuting it. |
| 18 | `12-quantization-compression/lottery-ticket-existence-at-initialization` | W3087194612 Pruning Neural Networks at Initialization: Why… (2020) | refutes | partly | Current pruning-at-init methods fall short of post-training pruning; not a proof that tickets cannot be found at initialisation. |
| 19 | `12-quantization-compression/non-uniform-quantization-grid-optimality` | W4380558630 NF4 Isn't Information Theoretically Optimal (an… (2023) | refutes | correct | Shows NF4 is not information-theoretically optimal (value distribution depends on block size); contradicts a specific optimality claim. |
| 20 | `12-quantization-compression/perplexity-sufficiency-compression-metric` | W4387322997 Compressing LLMs: The Truth is Rarely Pure and… (2023) | refutes | correct | Statement names the implicit sufficiency claim; LLM-KICK shows matched perplexity with sharp knowledge-task loss (e.g. 25-30% sparsity). |
| 21 | `20-interpretability/causal-faithfulness-metrics` | W4400612107 Transformer Circuit Faithfulness Metrics are no… (2024) | refutes | partly | Existing circuit faithfulness scores depend on ablation choices; negative result on current metrics, not on the problem. |
| 22 | `22-safety-robustness/certified-robustness-beyond-smoothing-radii` | W4223990786 Planting Undetectable Backdoors in Machine Lear… (2022) | refutes | partly | Undetectable backdoors are a barrier to certifying a model supplied by an untrusted trainer; does not bound smoothing radii for honest training. |
| 23 | `22-safety-robustness/jailbreak-robustness-unbounded-prompt-space` | W4393946427 Jailbreaking Leading Safety-Aligned LLMs with S… (2024) | refutes | partly | 100% ASR on many aligned models shows current defences break; does not show robustness or certification impossible. |
| 24 | `22-safety-robustness/jailbreak-robustness-unbounded-prompt-space` | W4405090820 Best-of-N Jailbreaking (2025) | refutes | partly | High attack success on deployed models shows current defences break; does not show robustness or certification impossible. |
| 25 | `22-safety-robustness/provable-unlearning-hazardous-capabilities` | W4403928578 An Adversarial Perspective on Machine Unlearnin… (2024) | refutes | partly | Recovers capabilities from RMU-unlearned models; refutes one method's claim, not the possibility of provable unlearning. |
| 26 | `22-safety-robustness/robustness-accuracy-tradeoff-law-or-artifact` | W3101700548 A Closer Look at Accuracy vs. Robustness (2020) | refutes | partly | Argues the tradeoff is an artifact on separated datasets; takes one side of the theory variant, which is an advance, not a refutation. |
| 27 | `23-privacy-memorization/distillation-privacy-barrier` | W7133228119 Students Parrot Their Teachers: Membership Infe… (2023) | refutes | correct | Statement names the folk claim that students are safer; membership inference shows distillation gives limited privacy. |
| 28 | `29-distillation/exposure-bias-sequence-distillation` | W3198652303 Exposure Bias versus Self-Recovery: Are Distort… (2021) | refutes | partly | Exposure bias is limited in open-ended LM generation; no distillation experiment. |
| 29 | `30-synthetic-data/counterfactual-augmentation-spurious-removal` | W3103651020 Counterfactually-Augmented SNLI Training Data D… (2020) | refutes | correct | Counterfactual augmentation did not improve generalisation over size-matched data on SNLI; one task. |
| 30 | `33-uncertainty-calibration/aleatoric-epistemic-identifiability` | W4226294010 Pitfalls of Epistemic Uncertainty Quantificatio… (2022) | refutes | partly | Second-order loss minimisation does not represent epistemic uncertainty faithfully; negative result for one method class. |
| 31 | `33-uncertainty-calibration/aleatoric-epistemic-identifiability` | W4415797714 Benchmarking Uncertainty Disentanglement: Speci… (2024) | refutes | partly | Benchmark finds no estimator disentangles in practice (ImageNet); does not show the split unidentifiable. |
| 32 | `33-uncertainty-calibration/cold-posterior-effect` | W3004547119 How Good is the Bayes Posterior in Deep Neural… (2020) | refutes | wrong | This is Wenzel et al. 2020, the paper that reports the cold posterior effect; it supports the statement. |
| 33 | `33-uncertainty-calibration/cold-posterior-effect` | W3159054876 What Are Bayesian Neural Network Posteriors Rea… (2021) | refutes | partly | Full-batch HMC: tempering not needed, effect largely from data augmentation; an explanation that contradicts Wenzel et al., itself contested. |
| 34 | `33-uncertainty-calibration/cold-posterior-effect` | W3166861954 Data augmentation in Bayesian neural networks a… (2021) | refutes | partly | Effect persists with principled augmentation; refutes the augmentation explanation, and supports the phenomenon. |
| 35 | `33-uncertainty-calibration/deep-ensembles-versus-bayesian-posteriors` | W7133245255 Deep Ensembles Work, but Are They Necessary? (2022) | refutes | partly | A larger single network matches ensemble uncertainty and robustness; challenges a premise, does not say what ensembles do. |

## DBMS (http://localhost:18088)

| # | Problem | Work | Verdict | Judgement | Reason |
|---|---|---|---|---|---|
| 1 | `01-relational-theory/cq-treewidth-submodular-width` | W2111829945 The complexity of homomorphism and constraint s… (2007) | solves | partly | Grohe 2007 closes the bounded-arity case (treewidth modulo homomorphic equivalence, under an FPT assumption); unbounded arity and counting/enumeration stay open. |
| 2 | `01-relational-theory/cq-treewidth-submodular-width` | W2143238590 Tractable Hypergraph Properties for Constraint… (2013) | solves | partly | Marx 2013 gives the FPT frontier (submodular width, under ETH) for unbounded arity; polynomial-time frontier and #CQ stay open. |
| 3 | `01-relational-theory/order-dependencies-implication` | W2168773517 Expressiveness and complexity of order dependen… (2013) | solves | partly | Settles coNP-completeness of list-based OD inference; approximate, bidirectional and set-based variants and optimizer use are untouched. |
| 4 | `01-relational-theory/query-determinacy-views` | W1894718966 The Hunt for a Red Spider: Conjunctive Query De… (2015) | solves | correct | Shows unrestricted CQ determinacy undecidable, which the statement names as the central open problem; rewriting and finite variants are separate. |
| 5 | `15-data-integration/crowd-er-question-selection` | W2106675345 Crowdsourcing algorithms for entity resolution (2014) | refutes | partly | Shows a prior strategy (Wang et al.) can be arbitrarily bad and gives strategies with guarantees; contradicts a prior result, not the problem. |
| 6 | `29-hardware-conscious-db/rdma-one-sided-structures` | W7171815341 Two-sided RDMA Striking Back for Disaggregated… (2026) | refutes | wrong | Lotus reports two-sided RDMA throughput over one-sided systems; it does not show correct one-sided indexes impossible. |

Per-item data and totals: `benchmarks/results/verdict-handcheck.json` (`fields.<ai|dbms>.totals.<verdict>.<judgement>`).
