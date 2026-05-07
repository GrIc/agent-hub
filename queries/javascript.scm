; JavaScript structural captures for tree-sitter.
; Follows the universal capture vocabulary defined in docs/roadmap/02_PHASE_GRAPHRAG_v2.md section 3.

; --- Classes ---
(class_declaration
  name: (identifier) @class.name
) @class.def

; --- Methods (inside class body) ---
(method_definition
  name: (property_identifier) @method.name
) @method.def

; --- Functions (top-level) ---
(function_declaration
  name: (identifier) @method.name
) @method.def

; --- Calls (simple: foo()) ---
(call_expression
  function: (identifier) @call.target
) @call.site

; --- Imports ---
(import_statement) @import.site
