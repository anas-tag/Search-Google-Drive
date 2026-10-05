"""Formats proposés dans l'interface et filtrés dans SQLite."""

FORMAT_EXTENSIONS = {
    "markdown": (".md",),
    "images": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tif", ".tiff", ".ico", ".avif", ".heic", ".heif"),
    "pdf": (".pdf",),
    "documents": (".txt", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".csv", ".tsv", ".ppt", ".pptx", ".odp"),
}

FORMAT_OPTIONS = (
    {"value": "all", "label": "Tous les formats", "icon": "⌕",
     "heading": "Recherche dans les tutoriels", "placeholder": "Ex. bootloader, résumé, Linux…",
     "hint": "Contenu Markdown, noms des fichiers et noms des dossiers."},
    {"value": "markdown", "label": "Markdown", "icon": "MD",
     "heading": "Recherche Markdown", "placeholder": "Ex. bootloader, firmware, résumé…",
     "hint": "Recherchez dans le contenu et les noms de vos fichiers Markdown (.md)."},
    {"value": "images", "label": "Images", "icon": "▧",
     "heading": "Recherche d’images", "placeholder": "Ex. schéma, capture, architecture…",
     "hint": "Recherchez une image par son nom de fichier. Le contenu des images n’est pas analysé."},
    {"value": "pdf", "label": "PDF", "icon": "PDF",
     "heading": "Recherche de PDF", "placeholder": "Ex. manuel, datasheet, référence…",
     "hint": "Recherchez un PDF par son nom de fichier. Le texte des PDF n’est pas indexé."},
    {"value": "documents", "label": "Documents", "icon": "DOC",
     "heading": "Recherche de documents", "placeholder": "Ex. notes, rapport, tableau…",
     "hint": "Texte, Word, tableurs et présentations : recherche par nom de fichier uniquement."},
    {"value": "other", "label": "Autres fichiers", "icon": "…",
     "heading": "Recherche d’autres fichiers", "placeholder": "Ex. archive, script, projet…",
     "hint": "Recherchez les fichiers dont le format n’appartient pas aux catégories précédentes, par leur nom."},
)
