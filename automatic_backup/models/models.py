# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions
from enum import Enum
import boto3
import botocore
import os
import re


class BackupTypes(Enum):
    s3 = ('s3', 'Amazon Web-Service S3')


class Configuration(models.Model):
    _name = 'automatic_backup.configuration'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    success_mail = fields.Char("If successful, mail to")
    error_mail = fields.Char("If error, mail to")

    backup_type = fields.Selection([BackupTypes.s3.value], required=True)
    upload_path = fields.Char("Path to upload", required=True)

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
        if self.backup_type == BackupTypes.s3.value[0]:
            self._backup_on_s3()

    def _backup_on_s3(self):
        if self.s3_access_key_id is False or self.s3_secret_access_key is False:
            raise exceptions.MissingError(
                "You need to add a AccessKey and a SecretAccessKey!")
        if self.s3_bucket_name is False:
            raise exceptions.MissingError(
                "You need to add a BucketName!")

        client = boto3.client(
            's3',
            aws_access_key_id=self.s3_access_key_id,
            aws_secret_access_key=self.s3_secret_access_key
        )
        filename = 'test.zip'
        path = os.path.join(self.upload_path, filename)
        content = 'test'
        try:
            client.put_object(
                Bucket=self.s3_bucket_name,
                Body=content,
                Key=path
            )
        except botocore.exceptions.ClientError as client_err:
            raise exceptions.ValidationError(
                client_err.response['Error']['Message'])
        self.message_post("No Error during upload. You can find the backup under the bucket {0} with the name {1}".format(self.s3_bucket_name, path))
