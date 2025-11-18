from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    # Champ pour lier les emplacements de transit à un entrepôt spécifique
    # Note: Ce champ est nommé transit_warehouse_id pour éviter un conflit avec le champ
    # warehouse_id calculé standard d'Odoo sur stock.location
    transit_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Entrepôt de Transit',
        help='Entrepôt associé à cet emplacement de transit. Obligatoire pour les emplacements de transit.'
    )

    @api.constrains('usage', 'transit_warehouse_id')
    def _check_transit_warehouse(self):
        """Vérifie que les locations de transit ont un entrepôt assigné"""
        for location in self:
            if location.usage == 'transit' and not location.transit_warehouse_id:
                raise ValidationError(
                    _("Un emplacement de transit doit avoir un entrepôt assigné.")
                )

    @api.model
    def _get_allowed_location_domain(self, warehouses):
        """
        Construit un domaine de restrictions pour les emplacements d'un utilisateur.

        Retourne un domaine qui autorise:
        - Les emplacements internes sous la racine de chaque entrepôt
        - Les emplacements de transit liés à chaque entrepôt via transit_warehouse_id
        - Les emplacements virtuels (view) sous la racine de chaque entrepôt
        - Les emplacements avec transit_warehouse_id assigné

        Args:
            warehouses: Recordset de stock.warehouse

        Returns:
            Liste de domaine Odoo
        """
        if not warehouses:
            return [('id', '=', 0)]  # Refuse tous les emplacements

        warehouse_ids = warehouses.ids
        warehouse_conditions = []

        # Construire une condition pour chaque entrepôt
        for warehouse in warehouses:
            if warehouse.view_location_id:
                warehouse_condition = [
                    '|',
                    '&', ('usage', '=', 'internal'), ('id', 'child_of', warehouse.view_location_id.id),
                    '|',
                    '&', ('usage', '=', 'transit'), ('transit_warehouse_id', '=', warehouse.id),
                    '&', ('usage', '=', 'view'), ('id', 'child_of', warehouse.view_location_id.id)
                ]
                warehouse_conditions.append(warehouse_condition)

        # Combiner toutes les warehouse_conditions avec OR
        if warehouse_conditions:
            restriction_domain = warehouse_conditions[0]
            for condition in warehouse_conditions[1:]:
                restriction_domain = ['|'] + restriction_domain + condition

            # Ajouter aussi les locations avec transit_warehouse_id assigné
            warehouse_location_domain = [('transit_warehouse_id', 'in', warehouse_ids)]
            restriction_domain = ['|'] + restriction_domain + warehouse_location_domain
        else:
            # Pas d'entrepôt avec view_location_id, mais on ajoute les locations par transit_warehouse_id
            restriction_domain = [('transit_warehouse_id', 'in', warehouse_ids)]

        return restriction_domain

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, **kwargs):
        """Surcharge de search pour filtrer les emplacements selon l'utilisateur"""
        user = self.env.user
        ctx_allowed = self.env.context.get('allowed_location_ids')

        def _is_internal_id_domain(domain):
            """True si domaine interne simple sur id (ex: [('id','in',ids)])"""
            if not domain:
                return False
            first = domain[0]
            if isinstance(first, (list, tuple)) and len(first) >= 3:
                return first[0] == 'id' and first[1] in ('in', 'not in', '=', '!=')
            return False

        # Si la vue fournit une liste d'IDs autorisés, l'utiliser comme domaine explicite
        # (contourne les restrictions normales - utilisé par les domaines des champs dans les vues)
        if ctx_allowed:
            forced = [('id', 'in', ctx_allowed)]
            args = args + forced if args else forced
            # NOTE: On applique les restrictions normales en addition si ctx_allowed est présent
            # Cela combine les deux filtres avec AND implicite (plus restrictif)
            # Si vous ne voulez que ctx_allowed, retournez ici.

        # Administrateurs et managers voient tout (sauf si ctx impose une liste ci-dessus)
        if not (user.has_group('base.group_system') or user.has_group('stock.group_stock_manager')):
            # Utilisateurs avec restriction d'entrepôt
            if user.has_group('restric_entrepot1.group_entrepot_restric'):
                # Eviter récursion sur les recherches internes
                if _is_internal_id_domain(args) or self.env.context.get('bypass_location_security'):
                    return super(StockLocation, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

                warehouses = user.warehouse_ids
                # Utiliser la méthode partagée pour construire le domaine de restrictions
                restriction_domain = self._get_allowed_location_domain(warehouses)
                args = args + restriction_domain if args else restriction_domain

        return super(StockLocation, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    # IMPORTANTE NOTE : Cette classe repose sur le fait que stock.picking.type a un champ 'warehouse_id'
    # qui lie chaque type d'opération à un entrepôt spécifique.

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, **kwargs):
        """
        Surcharge de search pour filtrer les types d'opération selon l'utilisateur.

        Logique de restriction :
        - Administrateurs (groupe system) et managers (groupe stock manager) : voir tous les types
        - Utilisateurs restreints (groupe_entrepot_restric) : voir seulement les types liés à leurs entrepôts assignés
        - Utilisateurs sans entrepôt assigné : ne voir aucun type

        La restriction utilise le champ 'warehouse_id' sur stock.picking.type pour déterminer
        quels types d'opération sont accessibles. Cela impacte les pickings créés par l'utilisateur,
        car le picking_type doit être sélectionné dans une vue.

        Note d'intégration : Cette restriction n'a d'effet que si stock.picking.type a un champ
        'warehouse_id' Many2one vers stock.warehouse. Si ce champ n'existe pas ou n'est pas correctement
        configuré, cette restriction ne fonctionnera pas.
        """
        user = self.env.user

        # Administrateurs et managers voient tout
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return super(StockPickingType, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

        # Utilisateurs avec restriction d'entrepôt
        if user.has_group('restric_entrepot1.group_entrepot_restric'):
            warehouses = user.warehouse_ids
            if warehouses:
                # Filtrer les types d'opération pour ne montrer que ceux des entrepôts assignés
                warehouse_ids = warehouses.ids
                restriction_domain = [('warehouse_id', 'in', warehouse_ids)]
                args = args + restriction_domain if args else restriction_domain
            else:
                # Pas d'entrepôt assigné = ne rien voir
                args = args + [('id', '=', 0)] if args else [('id', '=', 0)]

        return super(StockPickingType, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Champ pour marquer les transferts créés automatiquement par routes
    created_by_route = fields.Boolean(
        string="Créé par route",
        default=False,
        readonly=True,
        help="Indique si ce transfert a été créé automatiquement par une route Odoo. "
             "Les transferts créés par routes peuvent contourner certaines restrictions d'emplacements."
    )

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, **kwargs):
        """Surcharge de search pour filtrer les opérations selon l'utilisateur"""
        user = self.env.user

        # Administrateurs et managers voient tout
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return super(StockPicking, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

        # Utilisateurs avec restriction d'entrepôt
        if user.has_group('restric_entrepot1.group_entrepot_restric'):
            warehouses = user.warehouse_ids
            if warehouses:
                # Filtrer les pickings pour ne montrer que ceux des entrepôts assignés
                warehouse_ids = warehouses.ids
                restriction_domain = [('picking_type_id.warehouse_id', 'in', warehouse_ids)]
                args = args + restriction_domain if args else restriction_domain
            else:
                # Pas d'entrepôt assigné = ne rien voir
                args = args + [('id', '=', 0)] if args else [('id', '=', 0)]

        return super(StockPicking, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

    # Champs techniques utilisés par la vue pour filtrer les emplacements affichés
    is_location_restricted = fields.Boolean(
        string='Restriction d\'emplacements active',
        compute='_compute_allowed_locations',
        store=False,
    )
    allowed_location_ids = fields.Many2many(
        comodel_name='stock.location',
        string='Emplacements autorisés',
        compute='_compute_allowed_locations',
        store=False,
    )

    def _is_location_allowed(self, location, warehouses):
        """
        Vérifie si une location est autorisée pour l'utilisateur restreint.

        Une location est autorisée si :
        1. Elle a un transit_warehouse_id assigné qui correspond à l'un des entrepôts
        2. Elle est interne ou virtuelle ET est un enfant de la racine d'un entrepôt

        Args:
            location: record stock.location
            warehouses: recordset stock.warehouse

        Returns:
            Boolean - True si la location est autorisée, False sinon
        """
        if not location or not warehouses:
            return False

        warehouse_ids = warehouses.ids

        # Cas 1: Location avec transit_warehouse_id assigné
        if location.transit_warehouse_id and location.transit_warehouse_id.id in warehouse_ids:
            return True

        # Cas 2: Location interne ou virtuelle descendante de la racine d'un entrepôt
        if location.usage in ('internal', 'view'):
            for warehouse in warehouses:
                if not warehouse.view_location_id:
                    continue
                # Vérifier si la location est enfant de la racine
                if location.id in self.env['stock.location'].with_context(bypass_location_security=True).search([
                    ('id', 'child_of', warehouse.view_location_id.id),
                    ('id', '=', location.id),
                ]).ids:
                    return True

        return False

    def _is_valid_inter_transit_location(self, location, warehouses):
        """
        Vérifie si une virtual location est un Inter-Transit valide pour les entrepôts
        Vérifie d'abord le champ transit_warehouse_id, puis le pattern du nom en fallback
        """
        if location.usage != 'view':
            return False

        # Cas 1: Vérifier le champ transit_warehouse_id directement (approche robuste)
        if location.transit_warehouse_id:
            warehouse_ids = [w.id for w in warehouses]
            return location.transit_warehouse_id.id in warehouse_ids

        # Cas 2: Fallback - vérifier le pattern Inter-Transit dans le nom
        complete_name = location.complete_name or ''
        if 'Inter-Transit' not in complete_name:
            return False

        # Vérifier si le warehouse name correspond à l'un des entrepôts
        for warehouse in warehouses:
            expected_pattern = f'Inter-Transit {warehouse.name}'
            if expected_pattern in complete_name:
                return True

        return False

    def _get_inter_transit_children_locations(self, warehouses):
        """
        Récupère tous les enfants directs des virtual locations Inter-Transit
        qui ont un transit_warehouse_id correspondant aux entrepôts assignés
        """
        warehouse_ids = [w.id for w in warehouses]

        # D'abord, chercher toutes les virtual locations Inter-Transit avec transit_warehouse_id
        inter_transit_parents = self.env['stock.location'].with_context(bypass_location_security=True).search([
            '&', ('usage', '=', 'view'),
            ('transit_warehouse_id', 'in', warehouse_ids)
        ])

        # Puis, chercher tous les enfants directs de ces locations qui ont aussi transit_warehouse_id
        children = self.env['stock.location']
        for parent in inter_transit_parents:
            parent_children = self.env['stock.location'].with_context(bypass_location_security=True).search([
                '&', ('location_id', '=', parent.id),
                ('transit_warehouse_id', 'in', warehouse_ids)
            ])
            children |= parent_children

        return children

    @api.depends('picking_type_id')
    def _compute_allowed_locations(self):
        """Calcule la liste d'emplacements autorisés pour l'utilisateur courant.
        Utilisé par les domaines de `location_id` et `location_dest_id` dans la vue.
        """
        user = self.env.user
        is_admin_or_manager = user.has_group('base.group_system') or user.has_group('stock.group_stock_manager')
        is_restricted_user = user.has_group('restric_entrepot1.group_entrepot_restric') and not is_admin_or_manager

        for picking in self:
            # reset
            picking.is_location_restricted = False
            picking.allowed_location_ids = [(5, 0, 0)]

            # Cas 1: Admin/manager → tout voir
            if is_admin_or_manager:
                all_locs = self.env['stock.location'].with_context(bypass_location_security=True).search([])
                picking.allowed_location_ids = [(6, 0, all_locs.ids)]
                continue

            # Cas 2: Non restreint ou pas un transfert interne → tout voir
            if (not is_restricted_user) or (not picking.picking_type_id) or (picking.picking_type_id.code != 'internal'):
                all_locs = self.env['stock.location'].with_context(bypass_location_security=True).search([])
                picking.allowed_location_ids = [(6, 0, all_locs.ids)]
                continue

            # Cas 3: Utilisateur restreint sur transfert interne → seulement emplacements des entrepôts assignés
            warehouses = user.warehouse_ids
            if not warehouses:
                # Pas d'entrepôt assigné = ne rien autoriser
                picking.allowed_location_ids = [(5, 0, 0)]
                picking.is_location_restricted = True
                continue

            # Collecter les emplacements autorisés en utilisant le domaine partagé
            restriction_domain = self.env['stock.location']._get_allowed_location_domain(warehouses)
            allowed = self.env['stock.location'].with_context(bypass_location_security=True).search(restriction_domain)
            picking.allowed_location_ids = [(6, 0, allowed.ids)]
            picking.is_location_restricted = True


    @api.constrains('location_dest_id', 'picking_type_id')
    def _check_location_dest_allowed(self):
        """
        Vérifie que l'emplacement de destination est autorisé.

        Exception: Les transferts créés automatiquement par des routes Odoo
        (created_by_route=True) sont autorisés même si la destination n'est
        pas dans les entrepôts assignés de l'utilisateur.
        """
        for picking in self:
            # Ignorer pour les transferts automatiques
            if self.env.context.get('skip_location_restriction'):
                continue

            # ✨ NOUVEAU: Bypasser la validation si créé par une route
            if picking.created_by_route:
                continue

            # Seulement pour les transferts internes
            if not picking.picking_type_id or picking.picking_type_id.code != 'internal':
                continue

            user = self.env.user

            # Administrateurs et managers ne sont pas restreints
            if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
                continue

            # Vérifier si l'utilisateur a une restriction
            if user.has_group('restric_entrepot1.group_entrepot_restric'):
                warehouses = user.warehouse_ids
                if not warehouses:
                    raise ValidationError(
                        _("Vous devez avoir au moins un entrepôt assigné pour créer des transferts internes.")
                    )

                location_dest = picking.location_dest_id

                # Vérifier si la destination est autorisée en utilisant la méthode partagée
                if location_dest:
                    if not picking._is_location_allowed(location_dest, warehouses):
                        warehouse_names = ', '.join([w.name for w in warehouses])
                        raise ValidationError(
                            _("L'emplacement de destination '%s' n'est pas autorisé. Vous ne pouvez sélectionner que les emplacements de vos entrepôts: %s")
                            % (location_dest.complete_name, warehouse_names)
                        )

    @api.onchange('picking_type_id')
    def _onchange_set_location_domains(self):
        """Impose explicitement les domaines des emplacements dans le formulaire.
        Ce retour de domaine s'applique même si d'autres vues héritées modifient
        les attributs de la vue.
        """
        allowed_ids = self.allowed_location_ids.ids if self.allowed_location_ids else []
        return {
            'domain': {
                'location_id': [('id', 'in', allowed_ids)],
                'location_dest_id': [('id', 'in', allowed_ids)],
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        """
        Crée les pickings avec validation des restrictions.
        Marque automatiquement created_by_route=True si créé par une route Odoo.
        """
        # Vérifier si le picking est créé par une route
        from_route = self.env.context.get('from_stock_rule', False)

        # Marquer created_by_route pour les pickings créés par routes
        if from_route:
            for vals in vals_list:
                vals['created_by_route'] = True

        return super().create(vals_list)

    def write(self, vals):
        """Valide le changement de location_id selon les restrictions"""
        if 'location_id' in vals:
            user = self.env.user
            # Administrateurs et managers non restreints
            if not (user.has_group('base.group_system') or user.has_group('stock.group_stock_manager')):
                # Appliquer seulement aux utilisateurs restreints
                if user.has_group('restric_entrepot1.group_entrepot_restric') and user.warehouse_ids:
                    for picking in self:
                        # Seulement pour transferts internes
                        if picking.picking_type_id and picking.picking_type_id.code == 'internal':
                            new_loc_id = vals['location_id']
                            if new_loc_id:
                                new_loc = self.env['stock.location'].with_context(bypass_location_security=True).browse(int(new_loc_id))
                                # Utiliser la méthode partagée pour vérifier si la location est autorisée
                                if not picking._is_location_allowed(new_loc, user.warehouse_ids):
                                    warehouse_names = ', '.join([w.name for w in user.warehouse_ids])
                                    raise ValidationError(_("L'emplacement source '%s' n'est pas autorisé. Vous ne pouvez utiliser que les emplacements de vos entrepôts: %s") % (new_loc.complete_name, warehouse_names))
        return super().write(vals)


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, **kwargs):
        """
        Surcharge de search pour filtrer les mouvements de stock selon l'utilisateur.

        Les mouvements de stock peuvent transiter par des locations virtuelles (views),
        donc cette recherche inclut :
        - Locations internes (stockage réel)
        - Locations avec transit_warehouse_id assigné

        NOTE: Cette restriction utilise location_id OU location_dest_id car les mouvements
        peuvent commencer et se terminer dans les locations des entrepôts assignés.

        Voir StockQuant._search() pour la différence avec les quantités.
        """
        user = self.env.user

        # Administrateurs et managers voient tout
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return super(StockMove, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

        # Utilisateurs avec restriction d'entrepôt
        if user.has_group('restric_entrepot1.group_entrepot_restric'):
            warehouses = user.warehouse_ids
            if warehouses:
                # Collecter toutes les locations autorisées pour les entrepôts assignés
                allowed_location_ids = self.env['stock.location']

                for warehouse in warehouses:
                    # Locations avec transit_warehouse_id assigné directement
                    warehouse_locations = self.env['stock.location'].with_context(bypass_location_security=True).search([
                        ('transit_warehouse_id', '=', warehouse.id)
                    ])
                    allowed_location_ids |= warehouse_locations

                    # Locations internes sous la racine de l'entrepôt
                    if warehouse.view_location_id:
                        internal_locations = self.env['stock.location'].with_context(bypass_location_security=True).search([
                            ('usage', '=', 'internal'),
                            ('id', 'child_of', warehouse.view_location_id.id)
                        ])
                        allowed_location_ids |= internal_locations

                allowed_location_ids = allowed_location_ids.ids

                # Domaine pour filtrer les mouvements:
                # location_id OU location_dest_id dans les locations autorisées
                restriction_domain = [
                    '|',
                    ('location_id', 'in', allowed_location_ids),
                    ('location_dest_id', 'in', allowed_location_ids)
                ]
                args = args + restriction_domain if args else restriction_domain
            else:
                # Pas d'entrepôt assigné = ne rien voir
                args = args + [('id', '=', 0)] if args else [('id', '=', 0)]

        return super(StockMove, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, **kwargs):
        """
        Surcharge de search pour filtrer les quantités selon l'utilisateur et ses entrepôts assignés.

        Les quantités devraient exister que dans des locations réelles (internal), pas dans
        les locations virtuelles (views). Cette recherche autorise :
        - Locations internes sous la racine de chaque entrepôt
        - Locations avec transit_warehouse_id assigné directement
        - Locations virtuelles (pour la complétude, mais peu de quantités réelles y sont)

        NOTE: Contrairement à StockMove._search(), celle-ci :
        1. Inclut VIEW locations (pour la complétude) mais les quantités réelles ne y seront pas
        2. Utilise location_id uniquement (pas location_dest_id comme les mouvements)
        3. N'exclut plus les enfants de "Physical Locations" (filtre supprimé - inutile et fragile)

        Voir StockMove._search() pour la différence avec les mouvements.
        """
        user = self.env.user

        # Administrateurs et managers voient tout
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return super(StockQuant, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)

        # Utilisateurs avec restriction d'entrepôt
        if user.has_group('restric_entrepot1.group_entrepot_restric'):
            warehouses = user.warehouse_ids
            if warehouses:
                # Collecter toutes les locations autorisées pour les entrepôts assignés
                allowed_location_ids = self.env['stock.location']

                for warehouse in warehouses:
                    # Locations avec transit_warehouse_id assigné directement
                    warehouse_locations = self.env['stock.location'].with_context(bypass_location_security=True).search([
                        ('transit_warehouse_id', '=', warehouse.id)
                    ])
                    allowed_location_ids |= warehouse_locations

                    # Locations internes et view sous la racine de l'entrepôt
                    if warehouse.view_location_id:
                        internal_locations = self.env['stock.location'].with_context(bypass_location_security=True).search([
                            '|',
                            '&', ('usage', '=', 'internal'), ('id', 'child_of', warehouse.view_location_id.id),
                            '&', ('usage', '=', 'view'), ('id', 'child_of', warehouse.view_location_id.id)
                        ])
                        allowed_location_ids |= internal_locations

                allowed_location_ids = allowed_location_ids.ids

                # Domaine pour filtrer les quantités: location_id doit être dans les locations autorisées
                # Le filtrage par usage='internal' et warehouse_id suffit pour exclure les locations virtuelles
                restriction_domain = [('location_id', 'in', allowed_location_ids)]
                args = args + restriction_domain if args else restriction_domain
            else:
                # Pas d'entrepôt assigné = ne rien voir
                args = args + [('id', '=', 0)] if args else [('id', '=', 0)]

        return super(StockQuant, self)._search(args, offset=offset, limit=limit, order=order, **kwargs)


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        """
        Override pour marquer les mouvements créés par routes.
        Cela permet de tracer l'origine du mouvement et d'appliquer des exceptions de sécurité.
        """
        move_values = super(StockRule, self)._get_stock_move_values(
            product_id, product_qty, product_uom, location_id, name, origin, company_id, values
        )

        # Ajouter un indicateur dans le context pour les pickings créés via cette route
        # Cela sera utilisé par StockPicking.create() pour marquer created_by_route=True
        if self.env.context.get('from_stock_rule'):
            move_values['from_stock_rule'] = True

        return move_values

    def _run_push(self, move):
        """
        Override de _run_push pour ajouter le context flag skip_location_restriction
        et permettre aux routes de créer des transferts inter-entrepôts.
        """
        # Ajouter le flag pour bypasser les restrictions lors de la création par route
        return super(StockRule, self.with_context(
            skip_location_restriction=True,
            from_stock_rule=True
        ))._run_push(move)

    def _run_pull(self, procurements):
        """
        Override de _run_pull pour ajouter le context flag skip_location_restriction
        et permettre aux routes de créer des transferts inter-entrepôts.
        """
        # Ajouter le flag pour bypasser les restrictions lors de la création par route
        return super(StockRule, self.with_context(
            skip_location_restriction=True,
            from_stock_rule=True
        ))._run_pull(procurements)
