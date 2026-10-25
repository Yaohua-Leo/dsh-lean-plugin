/-
  LeanAudit.lean — generic axiom / dependency audit for a Lean library.

  Usage (from the Lean project root, inside its Lake environment):

      lake env lean --run LeanAudit.lean <LibraryName> -- <Fully.Qualified.Name> ...

  For every target it prints one line

      LEANCHECK_JSON:{...}

  carrying the declaration's kind, its fully printed type, the module it comes
  from, its syntactic dependency closure and the axioms it depends on. The
  allowed-axiom whitelist is NOT applied here: this script reports, the project
  gate decides. Exit 0 means every target was found and reported; exit 1 means a
  target was missing from the environment; exit 2 means bad usage.

  This file is project-agnostic — it takes the library name and the targets on
  the command line. Do not hard-code project names here.
-/
import Lean
open Lean

namespace LeanAudit

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

/-- The constants syntactically reachable from a declaration's type and value. -/
def dependencies (env : Environment) (name : Name) : Array Name := Id.run do
  let mut seen : Std.HashSet Name := {}
  let mut order : Array Name := #[]
  let mut todo : Array Name := #[name]
  while !todo.isEmpty do
    let cur := todo.back!
    todo := todo.pop
    if seen.contains cur then
      continue
    seen := seen.insert cur
    order := order.push cur
    if let some ci := env.find? cur then
      for c in ci.type.getUsedConstants do
        if !seen.contains c then
          todo := todo.push c
      if let some v := ci.value? then
        for c in v.getUsedConstants do
          if !seen.contains c then
            todo := todo.push c
  return order

/-- The module a declaration was defined in, or `"unknown"`. -/
def moduleOf (env : Environment) (name : Name) : String :=
  match env.getModuleIdxFor? name with
  | some idx =>
    match env.header.moduleNames[idx]? with
    | some m => m.toString
    | none => "unknown"
  | none => "unknown"

/-- One report line for one target; `none` when the name is not in the environment. -/
def reportLine (target : Name) : CoreM (Option String) := do
  let env ← getEnv
  match env.find? target with
  | none => return none
  | some ci =>
    let ty ← Meta.MetaM.run' (Meta.ppExpr ci.type)
    let axioms ← collectAxioms target
    let deps := dependencies env target
    return some <| "LEANCHECK_JSON:" ++ Json.compress (Json.mkObj [
      ("name", Json.str target.toString),
      ("exists", Json.bool true),
      ("kind", Json.str (kindOf ci)),
      ("module", Json.str (moduleOf env target)),
      ("type", Json.str (ty.pretty 100000)),
      ("axioms", Json.arr (axioms.map (fun a => Json.str a.toString))),
      ("dependencies", Json.arr (deps.map (fun d => Json.str d.toString)))
    ])

end LeanAudit

def main (args : List String) : IO UInt32 := do
  match args with
  | [] =>
    IO.eprintln "usage: lake env lean --run LeanAudit.lean <Library> -- <decl>..."
    return 2
  | lib :: rest =>
    let targets := rest.filter (fun s => s != "--")
    if targets.isEmpty then
      IO.eprintln "LeanAudit: no targets given; refusing to report an empty audit as success"
      return 2
    let env ← importModules #[{ module := lib.toName }] {}
    let ctx : Core.Context := { fileName := "<LeanAudit>", fileMap := default }
    let st : Core.State := { env := env }
    let (lines, _) ← Core.CoreM.toIO (targets.mapM (fun t => LeanAudit.reportLine t.toName)) ctx st
    let mut missing : Array String := #[]
    for (t, l) in targets.zip lines do
      match l with
      | some line => IO.println line
      | none => missing := missing.push t
    if !missing.isEmpty then
      IO.eprintln s!"LeanAudit: not found in {lib}: {String.intercalate ", " missing.toList}"
      return 1
    return 0
