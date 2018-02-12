# -*- coding: utf-8 -*-
from odoo import http

# class AutomaticBackup(http.Controller):
#     @http.route('/automatic_backup/automatic_backup/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/automatic_backup/automatic_backup/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('automatic_backup.listing', {
#             'root': '/automatic_backup/automatic_backup',
#             'objects': http.request.env['automatic_backup.automatic_backup'].search([]),
#         })

#     @http.route('/automatic_backup/automatic_backup/objects/<model("automatic_backup.automatic_backup"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('automatic_backup.object', {
#             'object': obj
#         })