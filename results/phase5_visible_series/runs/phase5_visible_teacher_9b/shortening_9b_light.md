# Short reasoning of run `phase5_visible_teacher_9b` (`9b_light`)

Successful samples with more than 350 reasoning tokens (among the first 3 successes of a state in selection order) are rewritten by `teacher-9b` (adapter `None`, no thinking, 2 candidates at temperature 0.7, asked for at most 150 tokens, accepted up to 700). Each well-formed rewrite is prefilled as the policy's thoughts, the policy samples 4 steps at temperature 0.8, and the rewrite is sufficient if one of them succeeds in Lean. Rationalized: successful steps of no run for states without a thinking success, given a reasoning the same way. Git 5d825a08ca.

| mode | targets | rewrites | defects | checked | sufficient | targets passing | check samples succeeding | original tokens | shortest sufficient tokens | median ratio |
|---|---|---|---|---|---|---|---|---|---|---|
| compress | 312 | 624 | code_block 18, too_long 11, too_short 168, copies_step 4, restates_goal 6 | 417 | 334 | 67.3% | 58.4% | 543 | 199 | 0.37 |
| rationalize | 0 | 0 | none | 0 | 0 | 0.0% | 0.0% | 0 | 0 | 0.00 |

Examples the data selection would take: 2,585 of 6,143 states; sampled 4,527, compressed 150.

## Example rewrites

### compress, sufficient

Step: `have h0 := h 0 (fun _ => 1) (fun _ => 1) (fun _ => 1)
rw [Fin.sum_univ_succ, Fin.sum_univ_succ, Fin.sum_univ_succ] at h0
norm_num at h0`

Original: The goal is to prove `False` by contradiction given three systems of equations involving sums of powers. The hypothesis `h` states that if three sequences $a, b, c$ satisfy specific moment conditions with bases 2, 3, and 5 respectively, then their triple sum product equals $1/30$. However, the structure suggests that the actual values derived from the moment conditions for bases 2, 3, and 5 might lead to a contradiction when combined (perhaps the product should not be $1/30$, or the system is inconsistent).

Since the type signature uses `Fin (m + 1)` for indices up to $m$, but the exponents i …

Rewrite: To derive a contradiction, instantiate the hypothesis `h` with `m = 0` and constant sequences `a`, `b`, `c` equal to `1`. For `m=0`, the index type `Fin 1` has only `0`. The moment conditions simplify: $2^0 \cdot (a_0 \cdot 1) = 1 \implies a_0 = 1$, and similarly $b_0 = 1$, $c_0 = 1$. The conclusion of `h` then asserts that the triple sum $a_0 b_0 c_0 = 1$. However, `h` claims this sum equals `1/30`. This yields the equation `1 = 1/30`, which is false. The tactic `have h0 := h 0 ...` instantiates the hypothesis. Subsequent `rw` tactics expand the sums over `Fin 1` (which have one element) to their single terms, and `norm_num` simplifies the arithmetic to expose the contradiction `1 = 1/30`.

### compress, sufficient

Step: `nlinarith [sq_nonneg (4 * c - 9)]`

Original: The key idea is to derive a contradiction from the given inequality $4c > \frac{8}{9}c^2 + \frac{9}{2}$. We can rearrange this inequality into a quadratic form $Ac^2 + Bc + C < 0$ and analyze its discriminant or complete the square. Specifically, multiplying by 9 and rearranging terms yields $9 \cdot 4c > 8c^2 + 81/2$, or $16c > \frac{8}{9}c^2 + 9/2$. Wait, let's just multiply by 18 to clear denominators: $72c > 16c^2 + 81$. Rearranging gives $16c^2 - 72c + 81 > 0$. Let's check the discriminant of $16c^2 - 72c + 81$. The discriminant is $(-72)^2 - 4 \cdot 16 \cdot 81 = 5184 - 5184 = 0$. This m …

Rewrite: The hypothesis $4c > \frac{8}{9}c^2 + \frac{9}{2}$ is rearranged by multiplying by 18 to clear denominators, yielding $72c > 16c^2 + 81$. Moving all terms to one side gives $0 > 16c^2 - 72c + 81$. Recognizing the right-hand side as a perfect square, we factor it as $(4c - 9)^2$. The inequality thus becomes $0 > (4c - 9)^2$. Since the square of any real number is non-negative, $(4c - 9)^2 \ge 0$, making the strict inequality $0 > (4c - 9)^2$ impossible. We use `nlinarith` with the hint `sq_nonneg (4 * c - 9)` to automatically detect this contradiction derived from the non-negativity of squares.

### compress, sufficient

Step: `nlinarith [sq_nonneg (4 * c - 9)]`

Original: The key idea is to derive a contradiction from the given inequality $4c > \frac{8}{9}c^2 + \frac{9}{2}$. We can rearrange this inequality into a quadratic form $Ac^2 + Bc + C < 0$ and analyze its discriminant or complete the square. Specifically, multiplying by 9 and rearranging terms yields $9 \cdot 4c > 8c^2 + 81/2$, or $16c > \frac{8}{9}c^2 + 9/2$. Wait, let's just multiply by 18 to clear denominators: $72c > 16c^2 + 81$. Rearranging gives $16c^2 - 72c + 81 > 0$. Let's check the discriminant of $16c^2 - 72c + 81$. The discriminant is $(-72)^2 - 4 \cdot 16 \cdot 81 = 5184 - 5184 = 0$. This m …

Rewrite: The goal is to derive `False` from `4 * c > 8 / 9 * c ^ 2 + 9 / 2`. Multiply the inequality by 18 to clear denominators, yielding `72 * c > 16 * c ^ 2 + 81`. Rearranging terms gives `0 > 16 * c ^ 2 - 72 * c + 81`. Recognizing that `16 * c ^ 2 - 72 * c + 81` factors as `(4 * c - 9) ^ 2`, the inequality becomes `0 > (4 * c - 9) ^ 2`. Since the square of any real number is non-negative (`(4 * c - 9) ^ 2 ≥ 0`), the statement `0 > (4 * c - 9) ^ 2` is a contradiction. The `nlinarith` tactic will use the hint `sq_nonneg (4 * c - 9)` to automatically detect this non-negativity and derive the contradiction.

### compress, sufficient

Step: `have h_sq : 9 * (x * y * z) ≤ (x + y + z) ^ 2 := by
  nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x),
    mul_pos hx hy, mul_pos hy hz, mul_pos hz hx]
nlinarith [Real.sqrt_nonneg (x * y * z), Real.sq_sqrt (show 0 ≤ x * y * z by positivity), h_sq]`

Original: The goal is to prove the inequality $3\sqrt{xyz} \le x + y + z$ given the condition $\frac{27}{8}xyz \le (y+x)z + xy$ for positive real numbers $x, y, z$. The hypothesis relates the product $xyz$ to a specific combination of terms on the right-hand side. A standard approach for symmetric or near-symmetric inequalities involving square roots and sums is to square both sides to eliminate the radical, or to use the AM-GM inequality. Given the structure, squaring the goal leads to $9xyz \le (x+y+z)^2$, which expands to $9xyz \le x^2 + y^2 + z^2 + 2xy + 2yz + 2zx$. We need to show that the given hy …

Rewrite: To prove $3\sqrt{xyz} \le x+y+z$, we square both sides (valid since terms are positive) to reduce the goal to $9xyz \le (x+y+z)^2$. The hypothesis $\frac{27}{8}xyz \le (x+y)z + xy$ provides a bound on the product $xyz$. Expanding the squared goal yields $x^2 + y^2 + z^2 + 2xy + 2yz + 2zx \ge 9xyz$. The term $(x+y)z + xy = xz + yz + xy$ appears in the expansion. While the hypothesis gives $\frac{27}{8}xyz \le xz + yz + xy$, directly comparing this to the required $9xyz$ suggests we need to leverage the non-negativity of squared differences like $(x-y)^2$, $(y-z)^2$, and $(z-x)^2$. These terms allow us to relate the symmetric sum of squares to the mixed terms. Specifically, $x^2+y^2+z^2 \ge xy+yz+zx$. Combining this with the hypothesis and the specific coefficients, `nlinarith` can deduce that $9xyz \le x^2+y^2+z^2+2(xy+yz+zx)$ holds. Once $9xyz \le (x+y+z)^2$ is established, applying `Real.sq_sqrt` and `Real.sqrt_le_left` (via `nlinarith` with positivity facts) completes the proof of the original inequality.

### compress, sufficient

Step: `ring_nf`

Original: The goal is to prove the identity $w^2 = u^3 + v^3$ where $a = \sinh(x)$ and $b = \cosh(x)$. The key observation is that the variables are defined in terms of hyperbolic functions, which satisfy the fundamental identity $\cosh^2(x) - \sinh^2(x) = 1$, or in terms of $a$ and $b$, $b^2 - a^2 = 1$. The expressions for $u, v, w$ are complex polynomials in $a, b, c$. The most direct way to prove this equality in Lean, given that these are explicit algebraic definitions, is to use the `ring_nf` tactic to normalize both sides into a canonical polynomial form and then check for equality. If the differe …

Rewrite: The goal is to prove $w^2 = u^3 + v^3$ for $a = \sinh x$, $b = \cosh x$, and specific polynomial definitions of $u, v, w$ in terms of $a, b, c$. The hyperbolic functions satisfy $b^2 - a^2 = 1$. The expressions for $u, v, w$ are complex polynomials. Since `a` and `b` are defined as specific values, the equality holds if the algebraic identity holds modulo the relation $b^2 - a^2 - 1 = 0$ or if it holds universally as a polynomial in $a, b$. The most direct way to check this in Lean is to normalize the expressions. The `ring_nf` tactic expands and normalizes polynomial expressions into a canonical form. Applying `ring_nf` will expand both sides of the equation $w^2 = u^3 + v^3$. If the identity is purely algebraic and holds without needing the $b^2 - a^2 = 1$ constraint (or if the constraint is handled implicitly by the structure), `ring_nf` will close the goal. If the identity relies on $b^2 = 1 + a^2$, `ring_nf` will expose the discrepancy, allowing subsequent steps to utilize the hyperbolic identity. Therefore, `ring_nf` is the correct first step to simplify and compare the massive polynomial terms.

### compress, sufficient

Step: `ring_nf`

Original: The goal is to prove the identity $w^2 = u^3 + v^3$ where $a = \sinh(x)$ and $b = \cosh(x)$. The key observation is that the variables are defined in terms of hyperbolic functions, which satisfy the fundamental identity $\cosh^2(x) - \sinh^2(x) = 1$, or in terms of $a$ and $b$, $b^2 - a^2 = 1$. The expressions for $u, v, w$ are complex polynomials in $a, b, c$. The most direct way to prove this equality in Lean, given that these are explicit algebraic definitions, is to use the `ring_nf` tactic to normalize both sides into a canonical polynomial form and then check for equality. If the differe …

Rewrite: The goal is to prove $w^2 = u^3 + v^3$ where $a = \sinh(x)$, $b = \cosh(x)$, and $u, v, w$ are complex polynomials in $a, b, c$. We know $b^2 - a^2 = 1$. The expressions are too large for manual algebraic verification. `ring_nf` is the standard tactic to normalize algebraic expressions into a canonical polynomial form by expanding powers and products and collecting like terms. Since $a$ and $b$ are defined as specific functions of $x$, they satisfy the relation $b^2 - a^2 - 1 = 0$. However, `ring_nf` treats $a$ and $b$ as independent variables initially. If the identity holds purely algebraically without using $b^2 - a^2 = 1$ (which is rare for such specific structures unless the polynomial itself factors or simplifies drastically), `ring_nf` will verify it directly. If the equality relies on $b^2 = a^2 + 1$, `ring_nf` will expand the terms, and subsequent steps would use the relation $b^2 = a^2 + 1$. Given the structure, expanding is the necessary first step to reveal cancellations or to prepare for using the hyperbolic identity. Thus, applying `ring_nf` is the correct initial move to simplify the massive polynomials into a comparable form.

### compress, insufficient

Step: `have h0 := h 0 (fun _ => 1) (fun _ => 1) (fun _ => 1)
rw [Fin.sum_univ_succ, Fin.sum_univ_succ, Fin.sum_univ_succ] at h0
norm_num at h0`

Original: The goal is to prove `False` by contradiction given three systems of equations involving sums of powers. The hypothesis `h` states that if three sequences $a, b, c$ satisfy specific moment conditions with bases 2, 3, and 5 respectively, then their triple sum product equals $1/30$. However, the structure suggests that the actual values derived from the moment conditions for bases 2, 3, and 5 might lead to a contradiction when combined (perhaps the product should not be $1/30$, or the system is inconsistent).

Since the type signature uses `Fin (m + 1)` for indices up to $m$, but the exponents i …

Rewrite: To derive a contradiction, instantiate the hypothesis `h` with `m = 0` and constant functions equal to 1 for `a`, `b`, and `c`. With `m = 0`, the index type `Fin 1` contains only `⟨0, by decide⟩`, reducing all sums to single terms. The premises simplify to $2^0 \cdot (1 \cdot 0^0) = 1$, $3^0 \cdot (1 \cdot 0^0) = 1$, and $5^0 \cdot (1 \cdot 0^0) = 1$. Since $0^0 = 1$ and $x^0 = 1$ for $x > 0$, each equation holds ($1 = 1$). The conclusion of the instantiated hypothesis then becomes $1 \cdot 1 \cdot 1 = 1/30$, implying $1 = 1/30$. This is arithmetically false. The tactic `h 0 (fun _ => 1) (fun _ => 1) (fun _ => 1)` applies this instantiation. Subsequently, `Fin.sum_univ_succ` expands the sums over the singleton set `Fin 1` into the explicit term products. Finally, `norm_num` evaluates the arithmetic to reveal the contradiction $1 = 1/30$, allowing `False` to be introduced.

### compress, insufficient

Step: `have h_sq : 9 * (x * y * z) ≤ (x + y + z) ^ 2 := by
  nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x),
    mul_pos hx hy, mul_pos hy hz, mul_pos hz hx]
nlinarith [Real.sqrt_nonneg (x * y * z), Real.sq_sqrt (show 0 ≤ x * y * z by positivity), h_sq]`

Original: The goal is to prove the inequality $3\sqrt{xyz} \le x + y + z$ given the condition $\frac{27}{8}xyz \le (y+x)z + xy$ for positive real numbers $x, y, z$. The hypothesis relates the product $xyz$ to a specific combination of terms on the right-hand side. A standard approach for symmetric or near-symmetric inequalities involving square roots and sums is to square both sides to eliminate the radical, or to use the AM-GM inequality. Given the structure, squaring the goal leads to $9xyz \le (x+y+z)^2$, which expands to $9xyz \le x^2 + y^2 + z^2 + 2xy + 2yz + 2zx$. We need to show that the given hy …

Rewrite: To prove $3\sqrt{xyz} \le x+y+z$, it suffices to show $9xyz \le (x+y+z)^2$ since both sides are non-negative. The hypothesis $\frac{27}{8}xyz \le (y+x)z + xy$ provides a specific bound on the product $xyz$ relative to the pairwise sums. Squaring the target inequality yields $9xyz \le x^2 + y^2 + z^2 + 2(xy + yz + zx)$. We aim to use the hypothesis and standard non-negativity squares (like $(x-y)^2 \ge 0$) to force this result. Specifically, we hypothesize that the given constraint, combined with the fact that $x,y,z > 0$, implies the squared AM-GM inequality holds. The `nlinarith` tactic can verify $9xyz \le (x+y+z)^2$ by utilizing the hypothesis to bound the $xyz$ term and the squares of differences to handle the remaining polynomial terms. Once $9xyz \le (x+y+z)^2$ is established, applying `nlinarith` with the property $\sqrt{a} \le b \iff a \le b^2$ for $b \ge 0$ completes the proof.

### compress, insufficient

Step: `field_simp at h`

Original: The goal is to prove that $x + y \geq \frac{3 + 2\sqrt{2}}{5}$ given the constraint $\frac{1}{x + 3y} + \frac{1}{2x + y} = 1$ with $x, y > 0$. This is an optimization problem where we want to minimize $x+y$ subject to the given equation. A standard approach is to express one variable in terms of the other using the constraint, or to use inequalities like AM-GM, or to substitute variables to simplify the expression. Given the structure, introducing a substitution or using `nlinarith` with the square of the constraint might work, but a more direct algebraic manipulation or using `linear_independ …

Rewrite: To prove $x + y \geq \frac{3 + 2\sqrt{2}}{5}$ under the constraint $\frac{1}{x + 3y} + \frac{1}{2x + y} = 1$, we first manipulate the constraint algebraically. The term $\frac{3 + 2\sqrt{2}}{5}$ suggests a relationship involving the product or sum of the denominators $x+3y$ and $2x+y$. Directly applying nonlinear arithmetic (`nlinarith`) with the square root is difficult in its current fractional form. By applying `field_simp` at the hypothesis `h`, we clear the denominators, transforming the equation into a polynomial form $(x+3y)(2x+y) = (x+3y) + (2x+y)$. This simplifies the structure to a quadratic equation relating $x+y$ and the product of linear forms. This polynomial form allows us to express the product $(x+3y)(2x+y)$ explicitly in terms of $x+y$ (after letting $s=x+y$ and noting the product equals $s$ plus a constant shift relative to the variables) or directly bounds the product. Specifically, if we let $A = x+3y$ and $B = 2x+y$, the constraint becomes $1/A + 1/B = 1 \implies A+B = AB$. We also note that $5(x+y) = 2A+B = A + (A+B) = A+AB = A(1+B)$. The goal is to minimize this quantity subject to $A+B=AB$ and positivity. The cleared equation makes the relationship between the variables linear and quadratic, suitable for further algebraic manipulation or substitution to find the minimum value of $x+y$ using inequalities like AM-GM on the transformed variables, ultimately deriving the required lower bound.

### compress, insufficient

Step: `have h : ∀ (a b c : ℝ),
  -(a * b * c ^ 2 * 2) + (-(a * b ^ 2 * c * 2) - a ^ 2 * b * c * 2) + a ^ 2 * b ^ 2 * 2 + a ^ 2 * c ^ 2 * 2 + a ^ 4 +
          b ^ 2 * c ^ 2 * 2 +
        b ^ 4 +
      c ^ 4 ≥
    -(a * b ^ 3 * 2) + a * c ^ 3 * 2 + a ^ 3 * b * 2 + (-(a ^ 3 * c * 2) - b * c ^ 3 * 2) + b ^ 3 * c * 2 := by
  intros a b c
  ring_nf at *
  nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a),
             sq_nonneg (a + b), sq_nonneg (b + c), sq_nonneg (c + a),
             sq_nonneg (a - b + c), sq_nonneg (b - c + a), sq_nonneg (c - a + b)]
exact h a b c`

Original: The goal is to prove an inequality involving real numbers $a, b, c$. The expression is a polynomial inequality that likely represents a variation of Schur's inequality or a symmetric polynomial inequality. The key idea is to simplify the expression by grouping terms and potentially using known inequalities (like AM-GM) or algebraic manipulations to show the difference between the left-hand side (LHS) and right-hand side (RHS) is non-negative.

However, looking at the structure, it's often easier to move all terms to one side and show the resulting expression is non-negative. Let's define the d …

Rewrite: To prove the polynomial inequality, we first normalize the expressions by moving all terms to the left-hand side and applying `ring_nf` to combine like terms into a standard polynomial form. This reveals the difference between the sides. Next, we analyze the structure of this difference; it is a symmetric polynomial that can be bounded below by zero. We utilize the non-negativity of squares (`sq_nonneg`) for the variables and their various linear combinations (differences and sums). Specifically, we provide hypotheses for `sq_nonneg (a - b)`, `sq_nonneg (b - c)`, `sq_nonneg (c - a)`, and several other symmetric square terms. Finally, we apply `nlinarith` with these square witnesses, which allows the tactic to deduce that the non-negative sum of these squared terms implies the original inequality holds.

### compress, insufficient

Step: `have h₀ : 0 ∈ Set.Icc (0 : ℝ) 1 := by norm_num
have h₁ : 1 ∈ Set.Icc (0 : ℝ) 1 := by norm_num
have h₂ : (0 : ℝ) + 1 + 1 + 4 * 0 * 1 * 1 ≥ M * (0 * 1 + 1 * 1 + 1 * 0) := by
  apply H₄
  <;> simp [h₀, h₁]
have h₃ : (2 : ℝ) ≥ M := by
  linarith
have h₄ : M ≤ 2 := by linarith
exact h₄`

Original: To solve this problem, we need to find the maximum possible value of $M$ such that the inequality holds for all $a, b, c \in [0, 1]$. The proof state suggests we have already established some candidate values or properties for $M$ (specifically, checking cases where $a,b,c$ are 0 or 1). The goal `⊢ M ≤ 2` indicates we need to prove that $M$ cannot exceed 2. By substituting specific values into the inequality, we can derive an upper bound for $M$. For instance, setting $a=1, b=1, c=1$ gives $3 + 4 \ge M(3)$, which simplifies to $7 \ge 3M$, implying $M \le 7/3$. However, looking at the hypothese …

Rewrite: To prove $M \le 2$, we use the specific case $a=0, b=1, c=1$. First, establish $0 \in [0,1]$ and $1 \in [0,1]$ via `norm_num`. Then, apply hypothesis `H₄` (the instance for these values) to derive $0+1+1 + 4\cdot0\cdot1\cdot1 \ge M(0\cdot1 + 1\cdot1 + 1\cdot0)$, which simplifies to $2 \ge M$. Finally, rewrite this as $M \le 2$ using `linarith`. This step is chosen because the premise of `H₄` is trivially true, allowing direct extraction of an upper bound for $M$ without needing the general inequality.

### compress, insufficient

Step: `have h₀ : 0 ∈ Set.Icc (0 : ℝ) 1 := by norm_num
have h₁ : 1 ∈ Set.Icc (0 : ℝ) 1 := by norm_num
have h₂ : (0 : ℝ) + 1 + 1 + 4 * 0 * 1 * 1 ≥ M * (0 * 1 + 1 * 1 + 1 * 0) := by
  apply H₄
  <;> simp [h₀, h₁]
have h₃ : (2 : ℝ) ≥ M := by
  linarith
have h₄ : M ≤ 2 := by linarith
exact h₄`

Original: To solve this problem, we need to find the maximum possible value of $M$ such that the inequality holds for all $a, b, c \in [0, 1]$. The proof state suggests we have already established some candidate values or properties for $M$ (specifically, checking cases where $a,b,c$ are 0 or 1). The goal `⊢ M ≤ 2` indicates we need to prove that $M$ cannot exceed 2. By substituting specific values into the inequality, we can derive an upper bound for $M$. For instance, setting $a=1, b=1, c=1$ gives $3 + 4 \ge M(3)$, which simplifies to $7 \ge 3M$, implying $M \le 7/3$. However, looking at the hypothese …

Rewrite: To prove $M \le 2$, we instantiate the universal hypothesis with $a=0, b=1, c=1$. First, establish membership: $0 \in [0,1]$ and $1 \in [0,1]$ via `norm_num`. Then, apply the hypothesis `H₄` (the implication for these specific values) using these memberships to obtain the inequality $0+1+1 + 4\cdot0\cdot1\cdot1 \ge M(0\cdot1 + 1\cdot1 + 1\cdot0)$, which simplifies to $2 \ge M$. This directly yields $M \le 2$ by basic arithmetic (`linarith`). The choice of $a=0, b=1, c=1$ is strategic because it reduces the inequality to $2 \ge M$, providing the tight upper bound required.
