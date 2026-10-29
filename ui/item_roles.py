"""Item data roles that carry identifiers on table / list cells (SPEC-LOC-002
INV-3).

A cell's text is display text and will be translated; code that colours,
bolds, sorts or looks up a cell by what it MEANS reads the engine key from
``ITEM_KEY_ROLE`` instead. A plain int (Qt.ItemDataRole.UserRole is 256) so
modules can import it without QtCore.
"""

# The engine key of a cell: a planet name ("Sun"), an element ("Fire"), a
# modality ("Fixed"), a dignity code ("EX"), ...
ITEM_KEY_ROLE = 256 + 42
