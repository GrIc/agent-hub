; Java structural captures for tree-sitter.
; Follows the universal capture vocabulary defined in docs/roadmap/02_PHASE_GRAPHRAG_v2.md section 3.

; --- Classes, interfaces, enums, records ---
(class_declaration
  name: (identifier) @class.name
) @class.def

(interface_declaration
  name: (identifier) @class.name
) @class.def

(enum_declaration
  name: (identifier) @class.name
) @class.def

(record_declaration
  name: (identifier) @class.name
) @class.def

; --- Methods ---
(method_declaration
  name: (identifier) @method.name
) @method.def

; --- Fields ---
(field_declaration
  (variable_declarator
    name: (identifier) @field.name
  )
) @field.def

; --- Method calls ---
(method_invocation
  name: (identifier) @call.target
) @call.site

; --- Imports ---
(import_declaration
  (scoped_identifier) @import.path
) @import.site

; --- Annotations ---
(marker_annotation
  name: (identifier) @annotation.name
)

(annotation
  name: (identifier) @annotation.name
)
