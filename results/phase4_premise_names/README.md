# Premise names in the pinned environment

LeanDojo Benchmark 4 v10 (Mathlib `29dcec07`) lists 180,907 premises. In our pinned environment (Mathlib `d1d1e4b7`, `import Mathlib`) **174,259 exist** and **6,648 (3.7%) do not**. Names are compared as `Name.toString` against every constant of the environment; existing ones are printed with `PrettyPrinter.ppSignature` (5 failed to print and are dropped). 4 Lean processes, 323 s.

## By library

| Library | Premises | Missing | Share |
|---|---|---|---|
| Mathlib | 156,948 | 3,538 | 2.3% |
| lean4 | 19,634 | 2,588 | 13.2% |
| batteries | 2,883 | 182 | 6.3% |
| aesop | 1,122 | 245 | 21.8% |
| proofwidgets | 252 | 126 | 50.0% |
| Qq | 119 | 9 | 7.6% |
| importGraph | 15 | 0 | 0.0% |

## By LeanDojo kind

| Kind | Premises | Missing | Share |
|---|---|---|---|
| commanddeclaration | 163,879 | 5,579 | 3.4% |
| lemma | 16,969 | 1,083 | 6.4% |
| leanelabcommandcommandirreducibledef | 125 | 26 | 20.8% |

## Signature length (characters)

Full: `ppSignature` on one line without universe parameters. Compact (the prompt's form): instance arguments and implicit type variables dropped.

| Form | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|
| full | 192 | 158 | 357 | 685 | 4561 |
| compact | 129 | 104 | 233 | 487 | 4524 |

Missing examples: `isValidChar_UInt32`, `List.set_eq_of_length_le`, `Lean.JsonNumber.fromPositiveFloat!`, `Lean.Meta.isClassImp?`, `Lean.Meta.getFirstCtor`, `Lean.Meta.updateList`, `Lean.FuzzyMatching.fuzzyMatchCore`, `Lean.Meta.Match.expandBitVecValuePattern`, `Lean.Elab.Term.Do.mkUnit`, `Lean.IR.FreeIndices.withIndex`, `Lean.Meta.Grind.pushNewHEq`, `Lean.Elab.Command.findFieldInfo?`, `UInt16.toNat_mul`, `Lean.Meta.simpAssignmentArg`, `Batteries.HashMap.Imp.pairwise_replaceF`, `Aesop.extractProofRapp`, `Aesop.withPPAnalyze`, `List.getElem?_scanl_zero`, `Mathlib.Meta.FunProp.RefinedDiscrTree.GetUnify.M.run`, `RestrictGenTopology.of_continuous_prop`, `antilipschitzWith_inv_iff`, `CategoryTheory.largeCurriedCoyonedaLemma`, `contDiff_one_iff_hasFDerivAt`, `MeasureTheory.SignedMeasure.restrictNonposSeq_disjoint`, `CategoryTheory.Functor.CommShift.comp`, `Grp.SurjectiveOfEpiAuxs.comp_eq`, `AlgebraicGeometry.ΓSpec.toOpen_unit_app_val_c_app'`, `WeierstrassCurve.Affine.Y_sub_polynomialY`, `fastLegendreSym.eq`, `GromovHausdorff.candidates_le_maxVar`, `Surreal.Multiplication.mulOption_lt_mul_of_equiv`, `Subring.op_unop`, `SimpleGraph.IsTuranMaximal.card_parts_le`, `Finset.Colex.antisymm_aux`, `ManyOneDegree.le_trans`, `Matroid.comap`, `Subalgebra.linearEquivOp`, `Algebra.Presentation.baseChange`, `LLVM.getBasicBlockParent`, `Lean.IR.LLVM.size_tType`.

## Theorems LeanDojo lacks

The environment has 217,671 non-internal theorems. LeanDojo's corpus misses the ones that no source declaration introduces (`to_additive` translations, `alias`es, generated lemmas), among them common competition lemmas: `add_comm`, `mul_pos`, `mul_nonneg`, `Finset.sum_range_succ`, `abs_of_nonneg`, `sub_nonneg`. Of the 5,158 theorem names that traced validation-split competition steps mention, 25% are such theorems. Excluding compiler-generated companions (`proof_N`, `eq_N`, `match_N`, `sizeOf_spec`, `inj`, `injEq`) and metaprogramming namespaces (Lean, Mathlib, Aesop, Std, Batteries, ...), **25,556 theorems are added** to the retrieval corpus with code `theorem <signature>` synthesized from Lean's signature. Examples: `AEMeasurable.add`, `AddEquiv.neg_symm`, `AddMonoidHom.comp_zero`, `AddSubgroup.le_topologicalClosure`, `AddSubmonoid.op_coe`, `AlgebraicGeometry.Scheme.Pullback.gluing_J`, `Bimon_.toMon_Comon__map_hom`, `CategoryTheory.CechNerveTerminalFrom.wideCospan.limitIsoPi_inv_comp_pi_assoc`, `CategoryTheory.Equivalence.symm_inverse`, `CategoryTheory.GradedObject.mapTrifunctorMap_obj`, `CategoryTheory.Limits.Cocone.toOver_pt`, `CategoryTheory.Limits.coconeOfConeUnop_pt`, `CategoryTheory.Mat_.isoBiproductEmbedding_inv`, `CategoryTheory.OplaxFunctor.map₂_rightUnitor`, `CategoryTheory.ShortComplex.HomologyData.ofIsLimitKernelFork_iso`, `CategoryTheory.ShortComplex.rightHomologyι_descOpcycles_π_eq_zero_of_boundary_assoc`, `CategoryTheory.kernel_comp_cokernel_assoc`, `CommMon_.mul_comm`, `ContinuousMonoidHom.fst_toFun`, `Equiv.mulLeft₀_apply`, `Finset.Nonempty.bex`, `Finset.vadd_subset_vadd_left`, `Function.support_add`, `HomologicalComplex.natIsoSc'_inv_app_τ₂`, `IsBoundedLinearMap.toIsLinearMap`, `LawfulBitraversable.bitraverse_id_id`, `LocallyConstant.congrRightₗ_symm_apply_apply`, `MeasureTheory.Measure.singularPart_def`, `MonoidHom.flipHom_apply`, `NonUnitalSubsemiring.topEquiv_apply`, `PerfectField.separable_of_irreducible`, `Quaternion.rat_cast_imI`, `SemilatSupCat.dual_map`, `Shrink.linearEquiv_symm_apply`, `Sum.liftRel_iff`, `UniformConvexSpace.uniform_convex`, `add_eq_zero_iff_neg_eq`, `finsum_mem_add_distrib'`, `map_sum`, `selfAdjointPartL_apply_coe`.
