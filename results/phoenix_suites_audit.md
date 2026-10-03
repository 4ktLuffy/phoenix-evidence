Phoenix commit `9212a42a5`, 13 suites, 655 cases.

| suite | cases | gates | constant judge: acc / F1 / passes? | accuracy gate passes a judge 5 pts below | whole suite gate (acc + F1) passes it | exact gate needs | exact gate passes a judge 5 pts above | cases needed (80%) | exact gate passes a 97% judge | can tell two 97% judges apart? |
|---|---|---|---|---|---|---|---|---|---|---|
| faithfulness | 16 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.50 / 0.33 / no | 29% | 30% | 16/16 (100%) | 1% | 662 | 61% | no |
| tool_invocation | 31 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.52 / 0.34 / no | 31% | 30% | 27/31 (87%) | 8% | 662 | 100% | no |
| retrieval_relevance | 33 | accuracy ≥ 0.8, f1 ≥ 0.8 | 0.52 / 0.34 / no | 25% | 25% | 32/33 (97%) | 3% | 494 | 74% | no |
| conciseness | 34 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.73 / 0.42 / no | 31% | 16% | 30/34 (88%) | 5% | 662 | 100% | no |
| hallucination | 37 | accuracy ≥ 0.8, f1 ≥ 0.8 | 0.51 / 0.34 / no | 26% | 26% | 35/37 (95%) | 7% | 494 | 90% | no |
| pii_detection.synthetic | 40 | accuracy ≥ 0.8, f1 ≥ 0.8 | 0.60 / 0.38 / no | 30% | 19% | 38/40 (95%) | 5% | 494 | 88% | no |
| refusal | 40 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.57 / 0.36 / no | 31% | 21% | 34/40 (85%) | 10% | 662 | 100% | no |
| user_friction | 40 | accuracy ≥ 0.8, f1 ≥ 0.8 | 0.60 / 0.38 / no | 30% | 19% | 38/40 (95%) | 5% | 494 | 88% | no |
| completeness | 45 | accuracy ≥ 0.8, f1 ≥ 0.85 | 0.62 / 0.38 / no | 28% | 4% | 42/45 (93%) | 8% | 494 | 95% | no |
| tool_response_handling | 51 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.51 / 0.34 / no | 25% | 25% | 43/51 (84%) | 8% | 662 | 100% | no |
| toxicity | 58 | accuracy ≥ 0.8, f1 ≥ 0.8 | 0.50 / 0.33 / no | 18% | 19% | 53/58 (91%) | 12% | 494 | 99% | no |
| correctness | 80 | accuracy ≥ 0.7, f1 ≥ 0.7 | 0.50 / 0.33 / no | 21% | 15% | 65/80 (81%) | 12% | 662 | 100% | no |
| pii_detection | 150 | accuracy ≥ 0.9 | 1.00 / 1.00 / **yes** | 5% | 5% | 143/150 (95%) | 52% | 255 | 92% | no |

Pooled, the Jev post's 517 examples detect a judge-vs-judge difference of 0.024 at 80% power; 1 point needs 3059 examples, 2.7 points (96.7% vs 99.4%) needs 418.
