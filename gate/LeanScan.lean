/-
  LeanScan.lean — library-wide declaration scan for a Lean project gate.

  Usage (from the Lean project root, inside its Lake environment):

      lake env lean --run LeanScan.lean <LibraryName> -- \
          [--own <ModulePrefix>]... [--min-type-chars N]

  For every declaration whose module starts with one of the `--own` prefixes it
  prints one line

      LEANSCAN_JSON:{...}

  with the declaration's kind, module, normalized printed type and whether its
  axiom closure reaches `sorryAx`.

  Why this exists: the axiom audit in LeanAudit.lean only looks at the configured
  targets, so a `sorry` inside a helper definition that a target happens to use
  shows up as `sorryAx` late, and a duplicate restatement of a result is never
  reported at all. This scan is the machine-checkable half of that: it reports
  the whole library, and the project gate decides what fails.

  `--own` is required to tell project modules from dependency modules (Mathlib
  modules share the same environment). With no `--own`, nothing is printed and
  the exit status is 2, so an empty scan can never look like a clean scan.

  Exit 0: scanned, one line per declaration. 1: bad arguments. 2: no --own given.
-/
import Lean
open Lean

namespace LeanScan

/-- Kind tag of a constant, matching the strings the project gate reports. -/
def kindOf (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo _  => "axiom"
  | .defnInfo _   => "def"
  | .thmInfo _    => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _   => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _   => "constructor"
  | .recInfo _    => "recursor"

/-- The module a declaration was defined in, or `unknown`. -/
def moduleOf (env : Environment) (name : Name) : String :=
  match env.getModuleIdxFor? name with
  | some idx =>
    match env.header.moduleNames[idx]? with
    | some m => m.toString
    | none => "unknown"
  | none => "unknown"

/-- Collapse every whitespace run to one space, so hashing on the gate side is
    stable against pretty-printer line wrapping. -/
def normalize (s : String) : String := Id.run do
  let mut out : String := ""
  let mut pendingSpace := false
  for c in s.toList do
    if c.isWhitespace then
      pendingSpace := true
    else
      if pendingSpace && !out.isEmpty then
        out := out.push ' '
      pendingSpace := false
      out := out.push c
  return out

/-- Names in the axiom closure of `name` that are not definitions. -/
def axiomClosure (name : Name) : CoreM (Array Name) :=
  collectAxioms name

end LeanScan

def main (args : List String) : IO UInt32 := do
  let mut lib : Option String := none
  let mut own : List String := []
  let mut minTypeChars : Nat := 0
  let mut rest := args
  while !rest.isEmpty do
    match rest with
    | [] => break
    | a :: tail =>
      rest := tail
      if a == "--" then
        continue
      else if a == "--own" then
        match rest with
        | p :: tail2 =>
          own := own ++ [p]
          rest := tail2
        | [] =>
          IO.eprintln "LeanScan: --own needs a module prefix"
          return 1
      else if a == "--min-type-chars" then
        match rest with
        | n :: tail2 =>
          minTypeChars := n.toNat!
          rest := tail2
        | [] =>
          IO.eprintln "LeanScan: --min-type-chars needs a number"
          return 1
      else if lib.isNone then
        lib := some a
      else
        IO.eprintln s!"LeanScan: unexpected argument {a}"
        return 1

  let some library := lib
    | IO.eprintln "usage: lake env lean --run LeanScan.lean <Library> -- --own <Prefix>"
      return 1
  if own.isEmpty then
    IO.eprintln "LeanScan: no --own prefix; refusing to report an empty scan as a clean scan"
    return 2

  let env ← importModules #[{ module := library.toName }] {}
  let ctx : Core.Context := { fileName := "<LeanScan>", fileMap := default }
  let st : Core.State := { env := env }
  let _ ← Core.CoreM.toIO (do
    let decls := env.constants.toList
    for (name, ci) in decls do
      let module := LeanScan.moduleOf env name
      if !own.any (fun p => module.startsWith p) then
        continue
      let ty ← Meta.MetaM.run' (Meta.ppExpr ci.type)
      let normalized := LeanScan.normalize (ty.pretty 100000)
      let axioms ← LeanScan.axiomClosure name
      let sorryAx := axioms.any (fun a => a == `sorryAx)
      IO.println <| "LEANSCAN_JSON:" ++ Json.compress (Json.mkObj [
        ("name", Json.str name.toString),
        ("kind", Json.str (LeanScan.kindOf ci)),
        ("module", Json.str module),
        ("type", Json.str normalized),
        ("typeChars", Json.num normalized.length),
        ("minTypeChars", Json.num minTypeChars),
        ("sorryAx", Json.bool sorryAx)
      ])) ctx st
  return 0
