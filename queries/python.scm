; Python structural captures for tree-sitter.
; Follows the universal capture vocabulary defined in docs/roadmap/02_PHASE_GRAPHRAG_v2.md section 3.

; --- Classes ---
(class_definition
  name: (identifier) @class.name
) @class.def

; --- Functions / methods (async uses same node type with 'async' child) ---
(function_definition
  name: (identifier) @method.name
) @method.def

; --- Calls (simple: len(x)) ---
(call
  function: (identifier) @call.target
) @call.site

; --- Imports (import X) ---
(import_statement
  (dotted_name) @import.path
) @import.site

; --- Imports (from X import Y) ---
(import_from_statement
  (dotted_name) @import.path
) @import.site

; --- Decorators (annotations) ---
(decorator
  (identifier) @annotation.name
)
