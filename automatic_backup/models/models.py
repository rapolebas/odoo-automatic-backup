# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, service
from enum import Enum
import boto3
import botocore
import os
import datetime


class BackupTypes(Enum):
    s3 = ('s3', 'Amazon Web-Service S3')


class Configuration(models.Model):
    _name = 'automatic_backup.configuration'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    success_mail = fields.Many2one('res.users', ondelete='set null')
    error_mail = fields.Many2one('res.users', ondelete='set null')

    backup_type = fields.Selection([BackupTypes.s3.value], required=True)
    upload_path = fields.Char("Path to upload", required=True)
    last_backup = fields.Datetime(readonly=True)
    last_message = fields.Char(readonly=True)
    last_path = fields.Char(readonly=True)

    show_s3 = fields.Boolean(compute='set_show_s3', store=False)
    s3_access_key_id = fields.Char("Access Key")
    s3_secret_access_key = fields.Char("Secret Key")
    s3_bucket_name = fields.Char("BucketName")

    @api.model
    def create(self, vals):
        vals = self.check_upload_path(vals)
        result = super(Configuration, self).create(vals)
        return result

    @api.multi
    def write(self, vals):
        self.ensure_one()
        vals = self.check_upload_path(vals)
        result = super(Configuration, self).write(vals)
        return result

    def check_upload_path(self, vals):
        if 'upload_path' in vals:
            vals['upload_path'] = vals['upload_path'].replace('\\', '/')
            if '/' == vals['upload_path'][0]:
                vals['upload_path'] = vals['upload_path'][1:]
            if '/' != vals['upload_path'][-1]:
                vals['upload_path'] = vals['upload_path'] + '/'
        return vals

    def set_show_s3(self):
        self.show_s3 = (self.backup_type == BackupTypes.s3.value[0])

    @api.onchange('backup_type')
    def onchange_backup_type(self):
        self.set_show_s3()

    @api.multi
    def btn_action_backup(self):
        self.ensure_one()
        try:
            if self.backup_type == BackupTypes.s3.value[0]:
                self._backup_on_s3()
                self.send_email('')
        except Exception as err:
            self.set_last_fields(err.args[0])
            self.message_post(err.args[0])
            self.send_email(err.args[0], success=False)

    def send_email(self, message, success=True):
        if ((success and self.success_mail.id is not False) or (not success and self.success_mail.id is not False)):
            template_name = 'backup_configuration_success_template' if success else 'backup_configuration_error_template'
            template = self.env.ref('automatic_backup.'+template_name)
            self.env['mail.template'].browse(template.id).send_mail(self.id, force_send=True)

    def _backup_on_s3(self):
        if self.s3_access_key_id is False or self.s3_secret_access_key is False:
            raise exceptions.MissingError(
                "AWS S3: You need to add a AccessKey and a SecretAccessKey!")
        if self.s3_bucket_name is False:
            raise exceptions.MissingError(
                "AWS S3: You need to add a BucketName!")

        client = boto3.client(
            's3',
            aws_access_key_id=self.s3_access_key_id,
            aws_secret_access_key=self.s3_secret_access_key
        )
        filename, content = self.get_backup()
        path = os.path.join(self.upload_path, filename)

        try:
            client.put_object(
                Bucket=self.s3_bucket_name,
                Body=content,
                Key=path
            )
        except botocore.exceptions.ClientError as client_err:
            raise exceptions.ValidationError(
                "AWS S3: " + client_err.response['Error']['Message'])
        else:
            message = ("AWS S3: No Error during upload. You can "
                      "find the backup under the bucket {0} with the "
                      "name {1}".format(self.s3_bucket_name, path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def get_backup(self, dbname=None, backup_format='zip'):
        if dbname is None:
            dbname = self._cr.dbname
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        filename = "%s_%s.%s" % (dbname, ts, backup_format)
        dump_stream = service.db.dump_db(dbname, None, backup_format)
        return filename, dump_stream

    def set_last_fields(self, message, path=None):
        if path is not None:
            self.last_path = path
            self.last_backup = datetime.datetime.now()
        self.last_message = message
