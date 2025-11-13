# Documentation du Modèle de Données - Module `restric_entrepot1`

**Version**: 1.5
**Framework**: Odoo ERP
**Objectif**: Système de contrôle d'accès hiérarchique basé sur les entrepôts pour la gestion des stocks

---

## Table des Matières

1. [Vue d'Ensemble](#vue-densemble)
2. [Architecture des Modèles](#architecture-des-modèles)
3. [Diagramme des Relations](#diagramme-des-relations)
4. [Matrice de Sécurité](#matrice-de-sécurité)
5. [Les 3 Profils Utilisateurs](#les-3-profils-utilisateurs)
6. [Logique de Domaine de Filtrage](#logique-de-domaine-de-filtrage)
7. [Les 5 Couches de Défense](#les-5-couches-de-défense)
8. [Mécanismes Anti-Récursion](#mécanismes-anti-récursion)
9. [Flux de Données Complet](#flux-de-données-complet)
10. [Points Clés du Modèle](#points-clés-du-modèle)

---

## Vue d'Ensemble

### Description Générale

Le module **`restric_entrepot1`** implémente un système sophistiqué de restriction d'accès aux emplacements de stock dans Odoo. Il permet de limiter la visibilité et les opérations des utilisateurs aux seuls emplacements appartenant à leurs entrepôts assignés.

### Principes Fondamentaux

- **Sécurité par défaut**: Les utilisateurs restreints ne voient que leurs emplacements autorisés
- **Défense en profondeur**: 5 couches de sécurité indépendantes et complémentaires
- **Transparence**: Le filtrage est automatique et invisible pour l'utilisateur
- **Performance**: Filtrage optimisé au niveau de la base de données via record rules
- **Flexibilité**: Les administrateurs et gestionnaires conservent un accès complet

### Dépendances

- `base` - Module de base Odoo
- `stock` - Module de gestion des stocks Odoo

---

## Architecture des Modèles

Le module étend **6 modèles Odoo** existants pour implémenter le système de restrictions.

### Modèle 1: `res.users` (Utilisateurs)

**Fichier**: `models/res_users.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `res.users`

#### Nouveaux Champs

| Nom | Type | Relation | Requis | Description |
|-----|------|----------|--------|-------------|
| `warehouse_ids` | Many2many | `stock.warehouse` | Non | Entrepôts assignés à l'utilisateur pour les restrictions d'emplacements |

#### Description

Ce modèle constitue le **point d'entrée** du système de restriction. Chaque utilisateur membre du groupe `group_entrepot_restric` peut avoir un ou plusieurs entrepôts assignés via le champ `warehouse_ids`.

**Logique métier**:
- Un utilisateur sans entrepôt assigné ne peut pas créer de transferts
- Un utilisateur peut avoir plusieurs entrepôts assignés
- Les administrateurs ne sont pas affectés par ce champ

---

### Modèle 2: `stock.location` (Emplacements)

**Fichier**: `models/stock_restrict_destination.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `stock.location`

#### Nouveaux Champs

| Nom | Type | Relation | Requis | Description |
|-----|------|----------|--------|-------------|
| `warehouse_id` | Many2one | `stock.warehouse` | Si `usage='transit'` | Entrepôt associé à l'emplacement de transit |

#### Méthodes

##### 1. `_check_transit_warehouse()` - Contrainte

```python
@api.constrains('usage', 'warehouse_id')
def _check_transit_warehouse(self)
```

**Déclenchement**: Lors de la création ou modification d'un emplacement
**Objectif**: Garantir que tous les emplacements de transit ont un entrepôt assigné
**Validation**: Lève une `ValidationError` si `usage='transit'` et `warehouse_id` est vide

##### 2. `_get_allowed_location_domain(warehouses)` - Helper statique

```python
@api.model
def _get_allowed_location_domain(self, warehouses)
```

**Paramètres**:
- `warehouses` (recordset) - Liste des entrepôts autorisés

**Retourne**: Domain Odoo (liste de tuples)

**Objectif**: Construire le domaine de filtrage pour les emplacements autorisés

**Logique**:
```
Emplacement autorisé SI:
    ├─ warehouse_id directement assigné à un des entrepôts
    └─ OU (usage='internal' ET child_of racine entrepôt)
    └─ OU (usage='transit' ET warehouse_id assigné)
    └─ OU (usage='view' ET child_of racine entrepôt)
```

##### 3. `_search()` - Override ORM

```python
@api.model
def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None)
```

**Objectif**: Intercepter toutes les recherches d'emplacements et appliquer le filtrage automatique

**Flux**:
1. Vérifier si l'utilisateur est admin/manager → Bypass
2. Vérifier le flag `bypass_location_security` → Bypass
3. Vérifier si l'utilisateur est dans `group_entrepot_restric`
4. Charger `user.warehouse_ids`
5. Construire le domaine restrictif via `_get_allowed_location_domain()`
6. Combiner avec le domaine existant (AND)
7. Retourner le recordset filtré

**Types d'emplacements gérés**:
- **internal**: Emplacements physiques de stockage
- **transit**: Emplacements de transit inter-entrepôts
- **view**: Emplacements virtuels/organisationnels

---

### Modèle 3: `stock.picking.type` (Types d'Opération)

**Fichier**: `models/stock_restrict_destination.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `stock.picking.type`

#### Nouveaux Champs

Aucun nouveau champ.

#### Méthodes

##### 1. `_search()` - Override ORM

```python
@api.model
def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None)
```

**Objectif**: Filtrer les types d'opération (réception, livraison, transfert interne) par entrepôt

**Logique**: Un utilisateur restreint ne voit que les types d'opération de ses entrepôts assignés via le champ `warehouse_id` du modèle `stock.picking.type`.

---

### Modèle 4: `stock.picking` (Transferts de Stock)

**Fichier**: `models/stock_restrict_destination.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `stock.picking`

#### Nouveaux Champs

| Nom | Type | Relation | Stocké | Dépendances | Description |
|-----|------|----------|--------|-------------|-------------|
| `is_location_restricted` | Boolean | - | Non | `picking_type_id` | Indique si les restrictions d'emplacements sont actives |
| `allowed_location_ids` | Many2many | `stock.location` | Non | `picking_type_id` | Liste des emplacements autorisés pour les sélecteurs UI |

#### Méthodes

##### 1. `_search()` - Override ORM

**Objectif**: Filtrer les transferts par entrepôt via la relation `picking_type_id.warehouse_id`

##### 2. `_is_location_allowed(location, warehouses)` - Helper

```python
def _is_location_allowed(self, location, warehouses)
```

**Paramètres**:
- `location` (recordset) - Emplacement à vérifier
- `warehouses` (recordset) - Entrepôts autorisés

**Retourne**: Boolean

**Objectif**: Vérifier si un emplacement spécifique est autorisé pour les entrepôts donnés

**Logique**:
- Vérifier `location.warehouse_id` directement
- Vérifier si `location.id` est dans les emplacements autorisés via le domaine

##### 3. `_is_valid_inter_transit_location(location, warehouses)` - Helper

**Objectif**: Valider les emplacements Inter-Transit virtuels

**Méthodes de validation**:
1. **Primaire**: Vérifier le champ `warehouse_id`
2. **Fallback**: Pattern matching sur le nom de l'emplacement

##### 4. `_get_inter_transit_children_locations(warehouses)` - Helper

**Objectif**: Récupérer tous les emplacements enfants des emplacements Inter-Transit virtuels filtrés par entrepôt

##### 5. `_compute_allowed_locations()` - Computed Field

```python
@api.depends('picking_type_id')
def _compute_allowed_locations(self)
```

**Objectif**: Calculer dynamiquement les emplacements autorisés pour chaque transfert

**Logique par type d'utilisateur**:

| Type Utilisateur | Conditions | Emplacements Autorisés |
|------------------|------------|------------------------|
| Admin/Manager | `base.group_system` OU `stock.group_stock_manager` | Tous |
| Non restreint | Pas dans `group_entrepot_restric` | Tous |
| Restreint avec entrepôt | Dans `group_entrepot_restric` + `warehouse_ids` non vide | Filtrés par `_get_allowed_location_domain()` |
| Restreint sans entrepôt | Dans `group_entrepot_restric` + `warehouse_ids` vide | Aucun |

##### 6. `_check_location_dest_allowed()` - Contrainte

```python
@api.constrains('location_dest_id', 'picking_type_id')
def _check_location_dest_allowed(self)
```

**Déclenchement**: Lors de la création ou modification de `location_dest_id` ou `picking_type_id`

**Objectif**: Valider que la destination choisie est dans les emplacements autorisés

**Conditions d'application**:
- Uniquement pour les transferts internes (`picking_type_id.code == 'internal'`)
- Ignore si flag `skip_location_restriction` actif dans le contexte
- Ignore si utilisateur admin/manager

**Erreur**: Lève une `ValidationError` en français si la destination n'est pas autorisée

##### 7. `_onchange_set_location_domains()` - Onchange

```python
@api.onchange('picking_type_id')
def _onchange_set_location_domains(self)
```

**Déclenchement**: Lors du changement du type d'opération dans le formulaire

**Objectif**: Retourner des domaines pour filtrer les champs `location_id` et `location_dest_id`

**Retour**:
```python
{
    'domain': {
        'location_id': [('id', 'in', allowed_location_ids)],
        'location_dest_id': [('id', 'in', allowed_location_ids)]
    }
}
```

##### 8. `create()` - Override

**Objectif**: Validation lors de la création de nouveaux transferts

##### 9. `write()` - Override

**Objectif**: Valider les changements de `location_id` pour les utilisateurs restreints sur les transferts internes

**Flux de validation**:
```
Détection changement location_id
         ↓
Vérifier si utilisateur restreint
         ↓
Vérifier si transfert interne
         ↓
Vérifier via _is_location_allowed()
         ↓
Lever ValidationError si invalide
```

---

### Modèle 5: `stock.move` (Mouvements de Stock)

**Fichier**: `models/stock_restrict_destination.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `stock.move`

#### Nouveaux Champs

Aucun nouveau champ.

#### Méthodes

##### 1. `_search()` - Override ORM

**Objectif**: Filtrer les mouvements de stock individuels

**Logique**: Un mouvement est visible si **SOIT** `location_id` **SOIT** `location_dest_id` appartient aux emplacements autorisés (logique OR).

**Domaine appliqué**:
```python
[
    '|',
    ('location_id', 'in', allowed_location_ids),
    ('location_dest_id', 'in', allowed_location_ids)
]
```

---

### Modèle 6: `stock.quant` (Quantités en Stock)

**Fichier**: `models/stock_restrict_destination.py`
**Type**: Extension du modèle core Odoo
**Héritage**: `stock.quant`

#### Nouveaux Champs

Aucun nouveau champ.

#### Méthodes

##### 1. `_search()` - Override ORM

**Objectif**: Filtrer les quantités en stock par emplacement

**Logique**: Seules les quantités dans les emplacements autorisés sont visibles (filtrage par `location_id` uniquement).

**Note**: Le filtre d'exclusion "Physical Locations" précédemment utilisé a été supprimé car trop fragile.

---

## Diagramme des Relations

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ARCHITECTURE GLOBALE                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────┐
│   res.users     │  Point d'entrée du système
│                 │
│ warehouse_ids   │◄────────┐
└─────────────────┘         │
                            │ Many2many (N utilisateurs ↔ M entrepôts)
                            │
        ┌───────────────────┴──────────────────┐
        │                                      │
        │                                      │
┌───────▼────────────┐              ┌──────────▼──────────┐
│ stock.warehouse    │              │  stock.location     │
│  (Core Odoo)       │◄─────────────┤                     │
│                    │  Many2one    │  warehouse_id       │
│ view_location_id   │  (transit    │  usage              │
│                    │   only)      │                     │
└────────┬───────────┘              └──────────┬──────────┘
         │                                     │
         │ Many2one                            │
         │                          ┌──────────▼──────────┐
         │                          │   Hiérarchie via    │
         │                          │   child_of pour:    │
         │                          │   - internal        │
         │                          │   - view            │
         │                          └─────────────────────┘
         │
         │
┌────────▼────────────┐
│ stock.picking.type  │  Types d'opération
│   (Core Odoo)       │  (réception, livraison, interne)
│                     │
│ warehouse_id        │
│ code                │
└────────┬────────────┘
         │
         │ Many2one
         │
┌────────▼─────────────────────────────────────┐
│              stock.picking                   │  Modèle central
│                                              │
│ Champs core:                                 │
│   - location_id           (Many2one)         │
│   - location_dest_id      (Many2one)         │
│   - picking_type_id       (Many2one)         │
│                                              │
│ Champs computed:                             │
│   - is_location_restricted    (Boolean)      │
│   - allowed_location_ids      (Many2many)    │
└────────┬─────────────────────────────────────┘
         │
         │ One2many
         │
┌────────▼────────────┐
│   stock.move        │  Mouvements individuels
│                     │
│ location_id         │
│ location_dest_id    │
│ product_id          │
│ product_uom_qty     │
└────────┬────────────┘
         │
         │ One2many
         │
┌────────▼────────────┐
│ stock.move.line     │  Lignes détaillées
│                     │
│ location_id         │
│ location_dest_id    │
│ qty_done            │
└─────────────────────┘
         │
         │ Affecte
         ▼
┌─────────────────────┐
│   stock.quant       │  Quantités en stock
│                     │
│ location_id         │
│ product_id          │
│ quantity            │
└─────────────────────┘
```

---

## Matrice de Sécurité

### Permissions par Modèle

| Modèle | Groupe | Lecture | Écriture | Création | Suppression |
|--------|--------|---------|----------|----------|-------------|
| `res.users` | `group_entrepot_restric` | ✅ | ❌* | ❌ | ❌ |
| `stock.location` | `group_entrepot_restric` | ✅ | ❌ | ❌ | ❌ |
| `stock.picking.type` | `group_entrepot_restric` | ✅ | ❌ | ❌ | ❌ |
| `stock.picking` | `group_entrepot_restric` | ✅ | ✅ | ✅ | ✅ |
| `stock.move` | `group_entrepot_restric` | ✅ | ✅ | ✅ | ✅ |
| `stock.move.line` | `group_entrepot_restric` | ✅ | ✅ | ✅ | ✅ |
| `stock.quant` | `group_entrepot_restric` | ✅ | ❌ | ❌ | ❌ |
| `stock.warehouse` | `group_entrepot_restric` | ✅ | ❌ | ❌ | ❌ |

*\* Les utilisateurs peuvent voir leurs propres données mais ne peuvent pas modifier les autres utilisateurs*

### Méthodes de Filtrage par Modèle

| Modèle | Méthode de Filtrage | Champs Utilisés | Logique |
|--------|---------------------|-----------------|---------|
| `stock.location` | `_search()` override + Record Rule | `usage`, `warehouse_id`, hiérarchie `child_of` | Internal/view: child_of root, Transit: warehouse_id |
| `stock.picking.type` | `_search()` override + Record Rule | `warehouse_id` | Égalité directe |
| `stock.picking` | `_search()` override + Record Rule | `picking_type_id.warehouse_id` | Via relation Many2one |
| `stock.move` | `_search()` override + Record Rule | `location_id` OR `location_dest_id` | Au moins un emplacement autorisé |
| `stock.move.line` | Record Rule uniquement | `move_id.location_id` OR `move_id.location_dest_id` | Via relation vers stock.move |
| `stock.quant` | `_search()` override + Record Rule | `location_id` | Égalité avec emplacements autorisés |

### Record Rules Définies

**Fichier**: `security/stock_restrict_destination_view_security.xml`

#### 1. `rule_stock_location_read_restric`

```xml
<record id="rule_stock_location_read_restric" model="ir.rule">
    <field name="model_id" ref="stock.model_stock_location"/>
    <field name="domain_force">[(1,'=',1)]</field>
    <field name="groups" eval="[(4, ref('group_entrepot_restric'))]"/>
    <field name="perm_read" eval="True"/>
</record>
```

**Objectif**: Éviter les erreurs d'accès sur les documents existants. Le filtrage réel est fait dans `_search()`.

#### 2. `rule_stock_picking_type_restric`

```xml
<field name="domain_force">[('warehouse_id', 'in', user.warehouse_ids.ids)]</field>
```

**Objectif**: Limiter aux types d'opération des entrepôts assignés.

#### 3. `rule_stock_picking_restric`

```xml
<field name="domain_force">[('picking_type_id.warehouse_id', 'in', user.warehouse_ids.ids)]</field>
```

**Objectif**: Limiter aux transferts des entrepôts assignés via le type d'opération.

#### 4. `rule_stock_move_restric`

```xml
<field name="domain_force">[
    '|', '|', '|',
    ('location_id', '=', False),
    '&', ('location_id.usage', '=', 'transit'),
         ('location_id.warehouse_id', 'in', user.warehouse_ids.ids),
    '&', ('location_dest_id.usage', '=', 'transit'),
         ('location_dest_id.warehouse_id', 'in', user.warehouse_ids.ids),
    '|',
    ('location_id.usage', 'in', ['internal', 'view']),
    ('location_dest_id.usage', 'in', ['internal', 'view'])
]</field>
```

**Objectif**: Filtrage complexe des mouvements selon les types d'emplacements et warehouse_id.

#### 5. `rule_stock_move_line_restric`

**Objectif**: Similaire à `rule_stock_move_restric` via la relation `move_id`.

#### 6. `rule_stock_quant_restric`

```xml
<field name="domain_force">[(1,'=',1)]</field>
```

**Objectif**: Éviter les erreurs d'accès. Le filtrage réel avec `child_of` est fait dans `_search()`.

---

## Les 3 Profils Utilisateurs

Le système reconnaît trois types d'utilisateurs avec des niveaux d'accès différents:

### Profil 1: Administrateur / Gestionnaire de Stock

**Groupes**:
- `base.group_system` (Administrateur système) **OU**
- `stock.group_stock_manager` (Gestionnaire d'inventaire)

**Caractéristiques**:
- ✅ Accès complet à tous les entrepôts
- ✅ Aucune restriction d'emplacements
- ✅ Peut voir et modifier tous les transferts
- ✅ Bypass automatique de tous les filtres de restriction

**Cas d'usage**: Supervision globale, configuration système, gestion multi-sites

---

### Profil 2: Utilisateur Restreint avec Entrepôt(s) Assigné(s)

**Groupes**:
- `restric_entrepot1.group_entrepot_restric` (Restriction d'entrepôt)

**Conditions**:
- `user.warehouse_ids` contient au moins un entrepôt

**Caractéristiques**:
- ✅ Accès uniquement aux emplacements de ses entrepôts assignés
- ✅ Peut créer et modifier des transferts internes
- ✅ Voit uniquement les transferts de ses entrepôts
- ❌ Ne peut pas voir les emplacements d'autres entrepôts
- ❌ Ne peut pas créer/modifier des emplacements
- ❌ Lecture seule sur les quantités en stock

**Types d'emplacements visibles**:
1. **Internal**: Emplacements physiques sous la racine de l'entrepôt (`child_of view_location_id`)
2. **Transit**: Emplacements de transit avec `warehouse_id` correspondant
3. **View**: Emplacements virtuels sous la racine de l'entrepôt (`child_of view_location_id`)

**Cas d'usage**: Opérateurs d'entrepôt, magasiniers, préparateurs de commandes

---

### Profil 3: Utilisateur Restreint sans Entrepôt Assigné

**Groupes**:
- `restric_entrepot1.group_entrepot_restric` (Restriction d'entrepôt)

**Conditions**:
- `user.warehouse_ids` est vide

**Caractéristiques**:
- ❌ Aucun emplacement visible
- ❌ Ne peut pas créer de transferts
- ❌ Accès minimal au système

**Cas d'usage**: Utilisateur temporairement désactivé, en attente d'affectation

---

### Comparaison des Profils

```
┌────────────────────────────────────────────────────────────────┐
│                    Matrice des Permissions                      │
├───────────────┬───────────────┬───────────────┬────────────────┤
│ Action        │ Admin/Manager │ Restreint +   │ Restreint sans │
│               │               │ Entrepôt      │ Entrepôt       │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Voir tous     │      ✅       │      ❌       │      ❌        │
│ emplacements  │               │               │                │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Voir          │      ✅       │      ✅       │      ❌        │
│ emplacements  │               │  (son entrepôt│                │
│ assignés      │               │   uniquement) │                │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Créer         │      ✅       │      ✅       │      ❌        │
│ transferts    │               │               │                │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Modifier      │      ✅       │      ✅       │      ❌        │
│ transferts    │               │  (son entrepôt│                │
│               │               │   uniquement) │                │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Créer/Modifier│      ✅       │      ❌       │      ❌        │
│ emplacements  │               │               │                │
├───────────────┼───────────────┼───────────────┼────────────────┤
│ Voir quantités│      ✅       │      ✅       │      ❌        │
│ en stock      │               │  (lecture     │                │
│               │               │   seule)      │                │
└───────────────┴───────────────┴───────────────┴────────────────┘
```

---

## Logique de Domaine de Filtrage

### Fonction Centrale: `_get_allowed_location_domain(warehouses)`

Cette méthode constitue la **source unique de vérité** pour la construction des domaines de filtrage d'emplacements.

#### Signature

```python
@api.model
def _get_allowed_location_domain(self, warehouses):
    """
    Construit le domaine pour filtrer les emplacements autorisés.

    Args:
        warehouses (recordset): Liste des entrepôts autorisés

    Returns:
        list: Domaine Odoo (liste de tuples et opérateurs)
    """
```

#### Étapes de Construction

```python
# 1. Extraire les IDs des entrepôts
warehouse_ids = warehouses.ids

# 2. Extraire les IDs des emplacements racines
root_location_ids = warehouses.mapped('view_location_id').ids

# 3. Construire le domaine composite
domain = [
    '|',  # OR principal
    ('warehouse_id', 'in', warehouse_ids),  # Cas 1: warehouse_id direct
    '|',  # OR secondaire
    '&',  # AND pour internal
        ('usage', '=', 'internal'),
        ('id', 'child_of', root_location_ids),
    '|',  # OR tertiaire
    '&',  # AND pour transit
        ('usage', '=', 'transit'),
        ('warehouse_id', 'in', warehouse_ids),
    '&',  # AND pour view
        ('usage', '=', 'view'),
        ('id', 'child_of', root_location_ids)
]
```

#### Visualisation de la Logique

```
Un emplacement est AUTORISÉ si:

    ┌─────────────────────────────────────────────┐
    │ warehouse_id ∈ entrepôts assignés          │
    └─────────────────────────────────────────────┘
                    OU
    ┌─────────────────────────────────────────────┐
    │ usage = 'internal' ET                      │
    │ id ∈ child_of(racine entrepôt)            │
    └─────────────────────────────────────────────┘
                    OU
    ┌─────────────────────────────────────────────┐
    │ usage = 'transit' ET                       │
    │ warehouse_id ∈ entrepôts assignés          │
    └─────────────────────────────────────────────┘
                    OU
    ┌─────────────────────────────────────────────┐
    │ usage = 'view' ET                          │
    │ id ∈ child_of(racine entrepôt)            │
    └─────────────────────────────────────────────┘
```

### Explication des Cas

#### Cas 1: Warehouse ID Direct

```python
('warehouse_id', 'in', warehouse_ids)
```

**Objectif**: Capturer tous les emplacements avec un lien direct vers l'entrepôt

**S'applique à**:
- Emplacements de transit avec `warehouse_id` explicite
- Tout emplacement ayant le champ `warehouse_id` rempli

#### Cas 2: Emplacements Internal

```python
'&',
    ('usage', '=', 'internal'),
    ('id', 'child_of', root_location_ids)
```

**Objectif**: Capturer les emplacements physiques de stockage

**Mécanisme**: Utilise l'opérateur `child_of` pour traverser la hiérarchie d'emplacements depuis la racine (`view_location_id`) de l'entrepôt

**Exemple de hiérarchie**:
```
WH/Stock (view_location_id)
├── WH/Stock/Shelf A (internal) ✅
│   ├── WH/Stock/Shelf A/Row 1 (internal) ✅
│   └── WH/Stock/Shelf A/Row 2 (internal) ✅
├── WH/Stock/Shelf B (internal) ✅
└── WH/Stock/Quality Control (internal) ✅
```

#### Cas 3: Emplacements Transit

```python
'&',
    ('usage', '=', 'transit'),
    ('warehouse_id', 'in', warehouse_ids)
```

**Objectif**: Capturer les emplacements de transit inter-entrepôts

**Mécanisme**: Filtrage direct par le champ `warehouse_id` (ajouté par le module)

**Exemple**:
```
Partners/Inter-Transit WH1 → WH2 (transit, warehouse_id=WH1) ✅
Partners/Inter-Transit WH2 → WH3 (transit, warehouse_id=WH2) ❌
```

#### Cas 4: Emplacements View

```python
'&',
    ('usage', '=', 'view'),
    ('id', 'child_of', root_location_ids)
```

**Objectif**: Capturer les emplacements virtuels/organisationnels

**Mécanisme**: Similaire aux emplacements internal, utilise `child_of` pour la hiérarchie

**Exemple**:
```
WH/Stock (view) ✅
├── WH/Stock/Zone A (view) ✅
│   └── WH/Stock/Zone A/Bin 1 (internal) ✅
└── WH/Stock/Zone B (view) ✅
```

---

### Exemple Complet

#### Contexte

**Utilisateur**: Jean Dupont
**Groupe**: `group_entrepot_restric`
**Entrepôts assignés**:
- Warehouse 1 (ID=1, view_location_id=10)
- Warehouse 2 (ID=2, view_location_id=20)

#### Domaine Généré

```python
[
    '|',
    ('warehouse_id', 'in', [1, 2]),
    '|',
    '&', ('usage', '=', 'internal'), ('id', 'child_of', [10, 20]),
    '|',
    '&', ('usage', '=', 'transit'), ('warehouse_id', 'in', [1, 2]),
    '&', ('usage', '=', 'view'), ('id', 'child_of', [10, 20])
]
```

#### Emplacements Résultants

| ID | Nom | Usage | warehouse_id | Parent | Visible ? |
|----|-----|-------|--------------|--------|-----------|
| 10 | WH1/Stock | view | - | - | ✅ (Cas 4) |
| 11 | WH1/Stock/Shelf A | internal | - | 10 | ✅ (Cas 2) |
| 12 | WH1/Stock/Shelf B | internal | - | 10 | ✅ (Cas 2) |
| 13 | Inter-Transit WH1 | transit | 1 | - | ✅ (Cas 3) |
| 20 | WH2/Stock | view | - | - | ✅ (Cas 4) |
| 21 | WH2/Stock/Shelf C | internal | - | 20 | ✅ (Cas 2) |
| 30 | WH3/Stock | view | - | - | ❌ (Pas dans entrepôts) |
| 31 | WH3/Stock/Shelf D | internal | - | 30 | ❌ (Parent non autorisé) |
| 32 | Inter-Transit WH3 | transit | 3 | - | ❌ (warehouse_id non autorisé) |

---

## Les 5 Couches de Défense

Le module implémente une architecture de **défense en profondeur** avec 5 couches de sécurité indépendantes et complémentaires.

```
┌────────────────────────────────────────────────────────────────┐
│                    ARCHITECTURE DE SÉCURITÉ                    │
│                        (5 Couches)                             │
└────────────────────────────────────────────────────────────────┘

    [Utilisateur tente une action]
              ↓
    ┌─────────────────────────────┐
    │ Couche 1: Model Access      │  Permissions CRUD
    │           Rights            │  (ir.model.access.csv)
    └─────────────────────────────┘
              ↓ Autorisé
    ┌─────────────────────────────┐
    │ Couche 2: Record Rules      │  Filtrage niveau DB
    │           (ir.rule)         │  (Domaines statiques)
    └─────────────────────────────┘
              ↓ Enregistrements filtrés
    ┌─────────────────────────────┐
    │ Couche 3: ORM _search()     │  Filtrage dynamique
    │           Override          │  (Contexte + hiérarchie)
    └─────────────────────────────┘
              ↓ Recordset restreint
    ┌─────────────────────────────┐
    │ Couche 4: View Domain       │  Restriction sélecteurs UI
    │           Constraints       │  (allowed_location_ids)
    └─────────────────────────────┘
              ↓ Choix limités
    ┌─────────────────────────────┐
    │ Couche 5: Constraint        │  Validation finale
    │           Validators        │  (@api.constrains)
    └─────────────────────────────┘
              ↓ Validation réussie
    [Action exécutée et sauvegardée]
```

### Couche 1: Model Access Rights

**Fichier**: `security/ir.model.access.csv`
**Niveau**: Permissions CRUD par modèle
**Type**: Sécurité grossière (coarse-grained)

#### Fonction

Définir les permissions de base (Create, Read, Update, Delete) pour chaque modèle par groupe d'utilisateurs.

#### Exemple

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_delete
access_stock_location_restric,stock.location.restric,stock.model_stock_location,group_entrepot_restric,1,0,0,0
access_stock_picking_restric,stock.picking.restric,stock.model_stock_picking,group_entrepot_restric,1,1,1,1
```

#### Rôle dans la Défense

- ✅ **Première barrière**: Empêche les actions non autorisées avant même la requête en base
- ✅ **Performance**: Vérification rapide au niveau du modèle
- ❌ **Limitation**: Ne peut pas filtrer par enregistrement (row-level)

---

### Couche 2: Record Rules (ir.rule)

**Fichier**: `security/stock_restrict_destination_view_security.xml`
**Niveau**: Filtrage au niveau enregistrement (row-level)
**Type**: Domaines statiques

#### Fonction

Appliquer des domaines de filtrage au niveau de la base de données pour chaque requête.

#### Exemple

```xml
<record id="rule_stock_picking_restric" model="ir.rule">
    <field name="name">Restriction picking par entrepôt</field>
    <field name="model_id" ref="stock.model_stock_picking"/>
    <field name="domain_force">[('picking_type_id.warehouse_id', 'in', user.warehouse_ids.ids)]</field>
    <field name="groups" eval="[(4, ref('group_entrepot_restric'))]"/>
    <field name="perm_read" eval="True"/>
</record>
```

#### Rôle dans la Défense

- ✅ **Filtrage automatique**: Appliqué automatiquement par l'ORM à chaque requête SQL
- ✅ **Performance**: Optimisé au niveau de la base de données (index, jointures)
- ✅ **Sécurité**: Impossible de contourner via l'API Odoo standard
- ❌ **Limitation**: Domaines statiques, difficile d'exprimer des logiques complexes (ex: `child_of`)

---

### Couche 3: ORM _search() Override

**Fichier**: `models/stock_restrict_destination.py`
**Niveau**: Filtrage dynamique avec contexte
**Type**: Logique Python

#### Fonction

Intercepter toutes les recherches ORM et injecter dynamiquement des domaines de filtrage basés sur le contexte et l'utilisateur.

#### Exemple

```python
@api.model
def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
    # Vérifier bypass
    if self.env.context.get('bypass_location_security'):
        return super()._search(args, offset, limit, order, count, access_rights_uid)

    # Vérifier si utilisateur restreint
    user = self.env.user
    if user.has_group('restric_entrepot1.group_entrepot_restric'):
        warehouses = user.warehouse_ids
        if warehouses:
            # Construire domaine restrictif
            restriction_domain = self._get_allowed_location_domain(warehouses)
            # Combiner avec domaine existant
            args = expression.AND([args, restriction_domain])

    return super()._search(args, offset, limit, order, count, access_rights_uid)
```

#### Rôle dans la Défense

- ✅ **Flexibilité**: Logique complexe en Python (ex: `child_of`, calculs dynamiques)
- ✅ **Contexte**: Peut adapter le filtrage selon le contexte (flags, utilisateur, etc.)
- ✅ **Complet**: S'applique à toutes les recherches sans exception
- ❌ **Performance**: Overhead Python à chaque requête
- ❌ **Complexité**: Risque de récursion infinie si mal implémenté

---

### Couche 4: View Domain Constraints

**Fichier**: `views/stock_restrict_destination_view.xml`
**Niveau**: Restriction des sélecteurs UI
**Type**: Domaines XML sur les champs

#### Fonction

Limiter les options disponibles dans les dropdowns et sélecteurs de l'interface utilisateur.

#### Exemple

```xml
<field name="location_id"
       domain="[('id', 'in', allowed_location_ids)]"
       context="{'allowed_location_ids': allowed_location_ids}"
       options="{'no_create': True, 'no_create_edit': True}"/>

<field name="location_dest_id"
       domain="[('id', 'in', allowed_location_ids)]"
       context="{'allowed_location_ids': allowed_location_ids}"/>
```

#### Rôle dans la Défense

- ✅ **Expérience utilisateur**: Empêche la sélection d'options invalides
- ✅ **Feedback immédiat**: L'utilisateur voit uniquement ses options valides
- ✅ **Prévention**: Réduit les erreurs utilisateur
- ❌ **Contournable**: Peut être bypassé via API/RPC (d'où les autres couches)

---

### Couche 5: Constraint Validators

**Fichier**: `models/stock_restrict_destination.py`
**Niveau**: Validation finale avant sauvegarde
**Type**: Décorateurs `@api.constrains`

#### Fonction

Valider que les données respectent les règles métier juste avant la sauvegarde en base de données.

#### Exemple

```python
@api.constrains('location_dest_id', 'picking_type_id')
def _check_location_dest_allowed(self):
    """Valide que la destination est autorisée pour les transferts internes."""
    # Ignorer si flag de bypass
    if self.env.context.get('skip_location_restriction'):
        return

    user = self.env.user
    # Bypass pour admin/manager
    if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
        return

    # Vérifier si utilisateur restreint
    if user.has_group('restric_entrepot1.group_entrepot_restric'):
        for picking in self:
            # Uniquement pour transferts internes
            if picking.picking_type_id.code == 'internal':
                warehouses = user.warehouse_ids
                if not self._is_location_allowed(picking.location_dest_id, warehouses):
                    raise ValidationError(_(
                        "L'emplacement de destination '%s' n'est pas autorisé "
                        "pour vos entrepôts assignés."
                    ) % picking.location_dest_id.display_name)
```

#### Rôle dans la Défense

- ✅ **Dernière ligne de défense**: Impossible de sauvegarder des données invalides
- ✅ **Messages clairs**: Feedback utilisateur explicite en cas d'erreur
- ✅ **Intégrité**: Garantit la cohérence des données en base
- ❌ **Performance**: Validation coûteuse juste avant sauvegarde
- ❌ **UX**: L'utilisateur découvre l'erreur tard dans le processus

---

### Tableau Récapitulatif

| Couche | Moment | Type | Bypassable | Performance | Complexité |
|--------|--------|------|------------|-------------|------------|
| 1. Model Access | Avant requête | Statique | ❌ | ⚡⚡⚡ | ⭐ |
| 2. Record Rules | Requête SQL | Statique | ❌ | ⚡⚡⚡ | ⭐⭐ |
| 3. _search() Override | ORM Python | Dynamique | Via contexte | ⚡⚡ | ⭐⭐⭐⭐ |
| 4. View Domains | UI uniquement | Dynamique | ✅ (via API) | ⚡⚡⚡ | ⭐⭐ |
| 5. Constraints | Avant sauvegarde | Dynamique | Via contexte | ⚡ | ⭐⭐⭐ |

---

### Principe de Défense en Profondeur

```
Si une couche échoue ou est contournée:
    ├─ Les autres couches compensent
    ├─ Pas de point de défaillance unique
    └─ Sécurité maximale garantie

Exemple: Attaque via RPC/API
    ├─ Couche 4 (View) bypassée ✅ (normal, pas d'UI)
    ├─ Couche 3 (_search) filtre les données ✅
    ├─ Couche 5 (Constraint) valide avant save ✅
    └─ Attaque bloquée
```

---

## Mécanismes Anti-Récursion

Le module doit gérer un problème critique: **les méthodes `_search()` ont besoin de chercher des emplacements pour construire leurs domaines, mais ces recherches déclenchent à nouveau `_search()`**, créant une **récursion infinie**.

### Solution: Context Flags

Le module utilise des **flags de contexte** pour signaler aux méthodes `_search()` qu'elles doivent bypasser la logique de restriction.

---

### Flag 1: `bypass_location_security`

#### Usage

```python
# Dans _search() pour chercher des emplacements sans restriction
allowed_locations = self.env['stock.location'].with_context(
    bypass_location_security=True
).search([
    ('usage', '=', 'internal'),
    ('id', 'child_of', warehouse.view_location_id.ids)
])
```

#### Vérification dans _search()

```python
@api.model
def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
    # Vérifier le flag de bypass
    if self.env.context.get('bypass_location_security'):
        # Sauter toute la logique de restriction
        return super()._search(args, offset, limit, order, count, access_rights_uid)

    # ... reste de la logique de filtrage ...
```

#### Flux

```
StockLocation._search() appelé
         ↓
Vérifier context.bypass_location_security
         ↓
    OUI ─────→ return super()._search()  [Pas de filtrage]
     │
    NON
     ↓
Construire domaine restrictif
     ↓
Besoin de chercher des locations internes
     ↓
Appeler .with_context(bypass_location_security=True).search()
     ↓
_search() rappelé avec flag=True
     ↓
Bypass détecté → Retour direct sans filtrage
     ↓
Récursion évitée ✅
```

#### Sécurité

⚠️ **Important**: Ce flag est interne et ne doit **JAMAIS** être exposé à l'utilisateur final ou via l'API publique. Il est uniquement utilisé pour les recherches internes du module.

---

### Flag 2: `skip_location_restriction`

#### Usage

```python
# Pour les processus automatisés qui doivent bypasser les contraintes
picking.with_context(skip_location_restriction=True).write({
    'location_dest_id': some_restricted_location.id
})
```

#### Vérification dans les Contraintes

```python
@api.constrains('location_dest_id', 'picking_type_id')
def _check_location_dest_allowed(self):
    """Valide que la destination est autorisée."""
    # Vérifier le flag de bypass
    if self.env.context.get('skip_location_restriction'):
        return  # Sauter toute validation

    # ... reste de la logique de validation ...
```

#### Cas d'Usage

1. **Migrations de données**
   ```python
   # Script de migration
   for picking in pickings_to_migrate:
       picking.with_context(skip_location_restriction=True).write({
           'location_dest_id': new_location.id
       })
   ```

2. **Processus automatisés Odoo**
   ```python
   # Workflow système qui déplace automatiquement des stocks
   stock_move._action_done(context={'skip_location_restriction': True})
   ```

3. **Import de données**
   ```python
   # Import CSV/Excel avec locations potentiellement hors restriction
   self.env['stock.picking'].with_context(
       skip_location_restriction=True
   ).create(vals_list)
   ```

#### Sécurité

⚠️ **Important**: Ce flag doit être utilisé **uniquement** dans des contextes sûrs et contrôlés (migrations, processus système). Ne jamais l'exposer à l'utilisateur final.

---

### Context Key 3: `allowed_location_ids`

#### Usage

```python
# Forcer une liste spécifique d'IDs autorisés
locations = self.env['stock.location'].with_context(
    allowed_location_ids=[1, 2, 3, 5, 8]
).search([('usage', '=', 'internal')])
```

#### Vérification dans _search()

```python
@api.model
def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
    # ... logique normale de restriction ...

    # Vérifier si IDs forcés dans le contexte
    if self.env.context.get('allowed_location_ids'):
        forced_ids = self.env.context['allowed_location_ids']
        # Combiner avec domaine existant (AND)
        args = expression.AND([
            args,
            [('id', 'in', forced_ids)]
        ])

    return super()._search(args, offset, limit, order, count, access_rights_uid)
```

#### Logique de Combinaison

```python
Domaine final = restriction_domain AND forced_ids_domain AND args

Exemple:
    restriction_domain: Emplacements de WH1 et WH2
    forced_ids: [1, 2, 3, 10, 11]
    args: [('usage', '=', 'internal')]

    Résultat: Emplacements qui sont:
        - Dans WH1 ou WH2 (restriction)
        - ET dans [1, 2, 3, 10, 11] (forced)
        - ET avec usage='internal' (args)
```

#### Cas d'Usage

1. **Précomputation UI**
   ```python
   # Dans _compute_allowed_locations()
   allowed_ids = self._get_allowed_locations().ids

   # Passer au contexte de la vue
   return {
       'context': {'allowed_location_ids': allowed_ids}
   }
   ```

2. **Tests unitaires**
   ```python
   # Tester avec un sous-ensemble spécifique
   locations = self.env['stock.location'].with_context(
       allowed_location_ids=[location1.id, location2.id]
   ).search([])
   ```

---

### Tableau Récapitulatif

| Flag/Context | Objectif | Impact | Sécurité | Usage |
|--------------|----------|--------|----------|-------|
| `bypass_location_security` | Éviter récursion `_search()` | Skip complet du filtrage | ⚠️ Interne uniquement | Recherches internes du module |
| `skip_location_restriction` | Bypass validation contraintes | Skip `@api.constrains` | ⚠️ Processus contrôlés | Migrations, imports, workflows |
| `allowed_location_ids` | Forcer IDs spécifiques | Filtrage additionnel (AND) | ✅ Sûr | UI, tests, précomputation |

---

### Exemple Complet: Éviter la Récursion

```python
class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        """Override pour filtrer les locations selon les restrictions."""

        # 🛡️ POINT 1: Vérifier bypass pour éviter récursion
        if self.env.context.get('bypass_location_security'):
            return super()._search(args, offset, limit, order, count, access_rights_uid)

        user = self.env.user

        # Admin/Manager bypass
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return super()._search(args, offset, limit, order, count, access_rights_uid)

        # Vérifier si utilisateur restreint
        if user.has_group('restric_entrepot1.group_entrepot_restric'):
            warehouses = user.warehouse_ids

            if warehouses:
                # 🚨 POINT 2: Ici on a besoin de chercher des locations
                # → RISQUE DE RÉCURSION si on appelle .search() directement

                # ✅ SOLUTION: Utiliser bypass_location_security
                internal_locations = self.env['stock.location'].with_context(
                    bypass_location_security=True  # 🔑 Flag pour éviter récursion
                ).search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', warehouses.mapped('view_location_id').ids)
                ])

                transit_locations = self.env['stock.location'].with_context(
                    bypass_location_security=True  # 🔑 Flag pour éviter récursion
                ).search([
                    ('usage', '=', 'transit'),
                    ('warehouse_id', 'in', warehouses.ids)
                ])

                # Construire le domaine final
                allowed_ids = (internal_locations | transit_locations).ids
                restriction_domain = [('id', 'in', allowed_ids)]

                # Combiner avec domaine existant
                args = expression.AND([args, restriction_domain])

        return super()._search(args, offset, limit, order, count, access_rights_uid)
```

---

## Flux de Données Complet

### Scénario: Création d'un Transfert Interne

Ce diagramme illustre le **flux complet** depuis la connexion de l'utilisateur jusqu'à la sauvegarde d'un transfert de stock, en passant par toutes les couches de sécurité.

```
┌─────────────────────────────────────────────────────────────────┐
│                  FLUX DE CRÉATION D'UN TRANSFERT                │
└─────────────────────────────────────────────────────────────────┘

[1] Utilisateur Jean se connecte à Odoo
                 ↓
[2] Système vérifie les groupes
                 ↓
        ┌────────────────────┐
        │ group_entrepot_    │ → OUI
        │ restric ?          │
        └────────────────────┘
                 ↓
[3] Charger user.warehouse_ids
                 ↓
    Jean a: [Warehouse 1, Warehouse 2]
                 ↓
[4] Jean navigue: Inventaire → Opérations → Transferts Internes
                 ↓
[5] Jean clique "Créer"
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║          FORMULAIRE DE TRANSFERT S'AFFICHE                ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[6] Champ picking_type_id chargé
                 ↓
    StockPickingType._search() intercepté (Couche 3)
                 ↓
    Filtrage: Types d'opération de WH1 et WH2 uniquement
                 ↓
    Jean voit: [Transfert Interne WH1, Transfert Interne WH2]
                 ↓
[7] Jean sélectionne: "Transfert Interne WH1"
                 ↓
[8] @api.onchange('picking_type_id') déclenché
                 ↓
    _onchange_set_location_domains() exécuté
                 ↓
[9] _compute_allowed_locations() calculé
                 ↓
    Appel: _get_allowed_location_domain([WH1, WH2])
                 ↓
    ┌─────────────────────────────────────────┐
    │ Domaine construit:                      │
    │ - Internal: child_of [WH1 root, WH2 root] │
    │ - Transit: warehouse_id in [1, 2]       │
    │ - View: child_of [WH1 root, WH2 root]   │
    └─────────────────────────────────────────┘
                 ↓
    StockLocation._search() avec bypass_location_security=True
                 ↓
    Résultat: allowed_location_ids = [10, 11, 12, 20, 21, 22]
                 ↓
[10] Vue applique domaines (Couche 4)
                 ↓
    location_id: domain=[('id', 'in', [10,11,12,20,21,22])]
    location_dest_id: domain=[('id', 'in', [10,11,12,20,21,22])]
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║  Jean voit uniquement les emplacements WH1 et WH2        ║
    ║  dans les dropdowns                                       ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[11] Jean sélectionne:
     - Source: WH1/Stock/Shelf A (ID=11)
     - Destination: WH2/Stock/Shelf C (ID=21)
                 ↓
[12] Jean clique "Sauvegarder"
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║                  VALIDATION EN COURS                      ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[13] StockPicking.create() appelé (Couche 5)
                 ↓
    Valeurs: {
        'picking_type_id': Transfert Interne WH1,
        'location_id': 11,
        'location_dest_id': 21
    }
                 ↓
[14] @api.constrains('location_dest_id') déclenché
                 ↓
    _check_location_dest_allowed() exécuté
                 ↓
    Vérifier: skip_location_restriction? → NON
    Vérifier: Utilisateur admin? → NON
    Vérifier: Transfert interne? → OUI
                 ↓
    Appel: _is_location_allowed(location_dest_id=21, warehouses=[WH1,WH2])
                 ↓
    Vérifier: 21 in allowed_location_ids? → OUI ✅
                 ↓
    Validation réussie ✅
                 ↓
[15] Record Rules appliquées (Couche 2)
                 ↓
    Domaine: [('picking_type_id.warehouse_id', 'in', [1, 2])]
    Vérification: WH1 in [1, 2]? → OUI ✅
                 ↓
[16] Model Access Rights vérifiées (Couche 1)
                 ↓
    group_entrepot_restric peut créer stock.picking? → OUI ✅
                 ↓
[17] INSERT en base de données
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║           TRANSFERT CRÉÉ AVEC SUCCÈS                      ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[18] Odoo retourne l'ID du nouveau transfert
                 ↓
[19] Vue redirige vers le formulaire du transfert créé
                 ↓
[20] Jean peut maintenant traiter le transfert
```

---

### Scénario: Tentative de Violation de Sécurité

```
┌─────────────────────────────────────────────────────────────────┐
│            TENTATIVE D'ACCÈS NON AUTORISÉ (via API)             │
└─────────────────────────────────────────────────────────────────┘

[1] Attaquant tente de créer un transfert via RPC/API
                 ↓
    POST /web/dataset/call_kw/stock.picking/create
    {
        'picking_type_id': 5,  # Transfert WH3 (non autorisé)
        'location_dest_id': 99  # Emplacement WH3 (non autorisé)
    }
                 ↓
[2] Requête arrive au serveur Odoo
                 ↓
[3] ⚠️ Couche 4 (View Domain) BYPASSÉE (pas d'UI)
                 ↓
[4] Model Access Rights vérifiées (Couche 1)
                 ↓
    group_entrepot_restric peut créer stock.picking? → OUI ✅
                 ↓
[5] StockPicking.create() appelé
                 ↓
[6] Record Rules appliquées (Couche 2)
                 ↓
    Domaine: [('picking_type_id.warehouse_id', 'in', user.warehouse_ids.ids)]
                 ↓
    Vérification après création:
    picking_type_id=5 → warehouse_id=3
    3 in user.warehouse_ids? → NON ❌
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║         AccessError: Vous ne pouvez pas accéder           ║
    ║         à cet enregistrement                              ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[7] TENTATIVE BLOQUÉE PAR RECORD RULE
                 ↓
[8] Si Record Rule contournée (impossible normalement):
                 ↓
    @api.constrains('location_dest_id') déclenché (Couche 5)
                 ↓
    _check_location_dest_allowed()
                 ↓
    location_dest_id=99 in allowed_location_ids? → NON ❌
                 ↓
    ╔═══════════════════════════════════════════════════════════╗
    ║     ValidationError: L'emplacement de destination        ║
    ║     n'est pas autorisé pour vos entrepôts assignés        ║
    ╚═══════════════════════════════════════════════════════════╝
                 ↓
[9] TENTATIVE BLOQUÉE PAR CONTRAINTE
                 ↓
    Transaction SQL rollback
                 ↓
[10] Aucun enregistrement créé
                 ↓
    SÉCURITÉ MAINTENUE ✅
```

---

### Points Clés du Flux

#### 1. Filtrage Automatique et Transparent

L'utilisateur ne voit **jamais** les emplacements non autorisés. Le filtrage se fait en amont, invisible.

#### 2. Validation Multi-Couches

Même si une couche est contournée (ex: UI bypass via API), les autres couches compensent.

#### 3. Performance Optimisée

- **Étapes 6, 9**: Filtrage ORM avec `bypass_location_security` pour éviter overhead
- **Étape 15**: Record rules au niveau SQL (index, optimisations DB)

#### 4. Messages Utilisateur Clairs

- **Étape 14**: `ValidationError` en français avec nom de l'emplacement
- L'utilisateur comprend pourquoi l'action est refusée

---

## Points Clés du Modèle

### Strengths (Forces)

#### 1. Défense en Profondeur

```
5 couches de sécurité indépendantes
    ├─ Même si une couche échoue
    ├─ Les autres compensent
    └─ Aucun point de défaillance unique
```

**Impact**: Sécurité maximale, résilience aux attaques

---

#### 2. Source Unique de Vérité

```python
_get_allowed_location_domain(warehouses)
    ├─ Appelé par: StockLocation._search()
    ├─ Appelé par: StockPicking._compute_allowed_locations()
    └─ Logique centralisée, pas de duplication
```

**Impact**: Facilité de maintenance, cohérence garantie

---

#### 3. Filtrage Transparent

```
Utilisateur recherche des emplacements
    ↓
_search() intercepte automatiquement
    ↓
Filtrage invisible pour l'utilisateur
    ↓
Résultats déjà filtrés
```

**Impact**: Expérience utilisateur fluide, pas de friction

---

#### 4. Robustesse du Lien Transit

**Avant** (Pattern Matching):
```python
if "Inter-Transit WH1" in location.name:  # ❌ Fragile
```

**Après** (Champ Direct):
```python
if location.warehouse_id.id in warehouse_ids:  # ✅ Robuste
```

**Impact**:
- Pas de dépendance aux conventions de nommage
- Indexable en base de données
- Multilingue (pas dépendant du nom)

---

#### 5. Performance au Niveau DB

```sql
-- Record Rule appliquée directement dans le WHERE SQL
SELECT * FROM stock_picking
WHERE picking_type_id IN (
    SELECT id FROM stock_picking_type
    WHERE warehouse_id IN (1, 2)  -- user.warehouse_ids
)
```

**Impact**:
- Utilisation des index
- Optimisations du query planner
- Pas de filtrage post-requête

---

### Considerations (Points d'Attention)

#### 1. Complexité Distribuée

```
Logique de restriction répartie sur:
    ├─ 6 modèles Python
    ├─ 3 fichiers de sécurité (CSV + 2 XML)
    ├─ 3 fichiers de vues XML
    └─ Total: ~1000 lignes de code
```

**Impact**:
- Courbe d'apprentissage élevée
- Nécessite compréhension globale
- Documentation essentielle

**Mitigation**:
- Ce document MODELISATION.md
- Commentaires inline dans le code
- Diagrammes de flux

---

#### 2. Synchronisation Multi-Endroits

**Logique de filtrage des transit locations en 3 endroits**:

1. `StockLocation._search()`:
   ```python
   ('usage', '=', 'transit'),
   ('warehouse_id', '=', warehouse.id)
   ```

2. `StockPicking._compute_allowed_locations()`:
   ```python
   [('usage', '=', 'transit'), ('warehouse_id', '=', warehouse.id)]
   ```

3. `StockPicking._check_location_dest_allowed()`:
   ```python
   if location_dest.warehouse_id and location_dest.warehouse_id.id in warehouse_ids
   ```

**Impact**: Risque de désynchronisation lors de modifications

**Mitigation**:
- Tests unitaires couvrant tous les chemins
- Documentation claire des points de synchronisation
- Code review rigoureux

---

#### 3. Performance des _search() Overrides

```python
@api.model
def _search(self, args, ...):
    # 🚨 Exécuté à CHAQUE recherche d'emplacements
    user = self.env.user
    if user.has_group('...'):  # Requête SQL
        warehouses = user.warehouse_ids  # Requête SQL + cache
        domain = self._get_allowed_location_domain(warehouses)  # Calcul
    # ...
```

**Impact**:
- Overhead sur chaque requête
- Peut impacter les imports massifs
- Multiplication des appels SQL

**Mitigation**:
- Utiliser `bypass_location_security` pour les imports
- Cache au niveau utilisateur (session)
- Profiling régulier avec `/web/webclient/load_menus`

---

#### 4. Gestion Soigneuse des Context Flags

```python
# ❌ DANGEREUX: Exposer à l'API publique
@http.route('/api/locations', type='json', auth='user')
def get_locations(self, bypass=False):
    return request.env['stock.location'].with_context(
        bypass_location_security=bypass  # ❌ Faille de sécurité
    ).search([])

# ✅ CORRECT: Usage interne uniquement
def _internal_get_all_locations(self):
    return self.env['stock.location'].with_context(
        bypass_location_security=True
    ).search([])
```

**Impact**: Risque de failles de sécurité si mal utilisé

**Mitigation**:
- Flags documentés comme "internes uniquement"
- Revue de code pour détecter les expositions
- Tests de sécurité

---

#### 5. Récursion et Stack Overflow

```python
# ❌ RISQUE: Oublier le flag de bypass
@api.model
def _search(self, args, ...):
    # ...
    internal_locs = self.search([...])  # ❌ Récursion infinie!
```

**Impact**:
- Crash de l'application
- Maximum recursion depth exceeded

**Mitigation**:
- Toujours utiliser `with_context(bypass_location_security=True)` dans `_search()`
- Tests unitaires spécifiques pour la récursion
- Monitoring des logs d'erreur

---

### Recommandations pour le Développement

#### ✅ À Faire

1. **Toujours tester avec les 3 profils utilisateurs**
   - Admin
   - Utilisateur restreint avec entrepôt
   - Utilisateur restreint sans entrepôt

2. **Utiliser les context flags correctement**
   - `bypass_location_security` uniquement dans les `_search()` internes
   - `skip_location_restriction` uniquement pour les processus système

3. **Synchroniser les 3 points de logique transit**
   - Si modification de la logique transit, vérifier les 3 endroits

4. **Documenter les modifications**
   - Mettre à jour ce document `MODELISATION.md`
   - Commenter le code pour les logiques complexes

5. **Écrire des tests**
   - Tests unitaires pour chaque méthode critique
   - Tests d'intégration pour les flux complets
   - Tests de sécurité pour les bypasses

---

#### ❌ À Éviter

1. **Ne jamais appeler `.search()` directement dans `_search()`**
   - Toujours utiliser le flag `bypass_location_security`

2. **Ne jamais exposer les context flags via API/RPC**
   - Risque de faille de sécurité critique

3. **Ne pas dupliquer la logique de `_get_allowed_location_domain()`**
   - Toujours appeler cette méthode centrale

4. **Ne pas modifier les record rules sans les `_search()` correspondants**
   - Risque de désynchronisation

5. **Ne pas bypasser les couches de sécurité en production**
   - Utiliser uniquement pour les migrations/imports contrôlés

---

## Glossaire

| Terme | Définition |
|-------|------------|
| **child_of** | Opérateur de domaine Odoo pour filtrer par hiérarchie parent-enfant |
| **Computed Field** | Champ calculé dynamiquement via méthode Python (non stocké en DB) |
| **Constraint** | Validation métier déclenchée avant sauvegarde en base de données |
| **Context Flag** | Variable passée dans le contexte Odoo pour modifier le comportement |
| **Domain** | Expression de filtrage Odoo (liste de tuples et opérateurs) |
| **Model Access Rights** | Permissions CRUD par modèle et groupe d'utilisateurs |
| **ORM** | Object-Relational Mapping - couche d'abstraction base de données |
| **Override** | Surcharge d'une méthode héritée pour modifier son comportement |
| **Record Rule** | Règle de filtrage au niveau enregistrement (row-level security) |
| **Recordset** | Collection d'enregistrements retournée par l'ORM Odoo |
| **Transit Location** | Emplacement virtuel pour les transferts inter-entrepôts |
| **View Location** | Emplacement virtuel/organisationnel (pas de stock physique) |

---

## Annexes

### Fichiers Clés du Module

```
restric_entrepot1/
├── __manifest__.py                         # Métadonnées du module
├── __init__.py                             # Initialisation Python
├── CLAUDE.md                               # Instructions pour Claude Code
├── MODELISATION.md                         # Ce document
│
├── models/
│   ├── __init__.py
│   ├── res_users.py                        # Extension res.users
│   └── stock_restrict_destination.py       # Logique principale (6 modèles)
│
├── security/
│   ├── ir.model.access.csv                 # Permissions CRUD
│   └── stock_restrict_destination_view_security.xml  # Groupe + Record Rules
│
└── views/
    ├── res_users_view.xml                  # Vue utilisateurs (champ warehouse_ids)
    ├── stock_restrict_destination_view.xml # Vue transferts (domaines)
    └── stock_location_view.xml             # Vue emplacements (champ warehouse_id)
```

---

### Commandes Utiles pour le Développement

#### Activer le mode développeur Odoo

```
URL: http://your-odoo-instance.com/web?debug=1
```

#### Mettre à jour le module

```bash
# Ligne de commande
odoo-bin -u restric_entrepot1 -d your_database

# Ou via l'interface
Apps → restric_entrepot1 → Upgrade
```

#### Tester avec différents utilisateurs

```python
# Dans un shell Odoo
user_admin = env.ref('base.user_admin')
user_restricted = env['res.users'].search([('login', '=', 'jean')])

# Basculer le contexte
env = env(user=user_restricted)
locations = env['stock.location'].search([])
```

---

### Contacts et Support

- **Documentation Odoo**: https://www.odoo.com/documentation/
- **Forum Odoo**: https://www.odoo.com/forum
- **GitHub Odoo**: https://github.com/odoo/odoo

---

*Document généré le 2025-11-13*
*Version du module: 1.5*
*Odoo version: 14.0+ (compatible 15.0, 16.0, 17.0)*
