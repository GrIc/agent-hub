; Go structural captures for tree-sitter.
; Follows the universal capture vocabulary defined in docs/roadmap/02_PHASE_GRAPHRAG_v2.md section 3.

; --- Types (struct, interface) ---
(type_declaration
  (type_spec
    name: (type_identifier) @class.name
  )
) @class.def

; --- Functions (top-level) ---
(function_declaration
  name: (identifier) @method.name
) @method.def

; --- Methods (func (r Receiver) MethodName) ---
(method_declaration
  name: (field_identifier) @method.name
) @method.def

; --- Calls (simple: foo()) ---
(call_expression
  (identifier) @call.target
) @call.site

; --- Calls (selector: pkg.Func() or r.Method()) ---
(call_expression
  (selector_expression
    (identifier)
    .
    (field_identifier) @call.target
  )
) @call.site

; --- Imports ---
(import_declaration
  (import_spec) @import.path
) @import.site

; --- Struct fields ---
(field_declaration
  name: (field_identifier) @field.name
) @field.def
