# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, service
from enum import Enum

import boto3
import botocore

import dropbox
from dropbox import exceptions as dropbox_exceptions

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

import owncloud

import os
import datetime



class BackupTypes(Enum):
    s3 = ('s3', 'Amazon Web-Service S3')
    dropbox = ('dropbox', 'Dropbox')
    google_drive = ('google_drive', 'Google Drive')
    owncloud = ('owncloud', 'OwnCloud')


class Configuration(models.Model):
    _name = 'automatic_backup.configuration'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    schedule_frequently = fields.Selection(string='Every', selection=[('days', 'Days'), ('weeks', 'Weeks')],
                                           default='weeks', required=1)
    schedule_number = fields.Integer(min=1, default=1, required=1)

    next_backup_time = fields.Datetime(store=0, required=1, readonly=1, compute='_compute_next_backup_time')
    success_mail = fields.Many2one('res.users', ondelete='set null')
    error_mail = fields.Many2one('res.users', ondelete='set null')

    cron_id = fields.Many2one('ir.cron', ondelete='cascade')

    backup_type = fields.Selection([
        BackupTypes.s3.value,
        BackupTypes.dropbox.value,
        BackupTypes.google_drive.value,
        BackupTypes.owncloud.value
    ], required=True)
    upload_path = fields.Char("Path to upload", required=True)
    last_backup = fields.Datetime(readonly=True)
    last_message = fields.Char(readonly=True)
    last_path = fields.Char(readonly=True)

    show_s3 = fields.Boolean(compute='set_show_s3', store=False)
    show_dropbox = fields.Boolean(compute='set_show_dropbox', store=False)
    show_owncloud = fields.Boolean(compute='set_show_owncloud', store=False)

    show_access_key = fields.Boolean(compute='set_show_access_key', store=False)
    show_secret_key = fields.Boolean(compute='set_show_secret_key', store=False)

    access_key_id = fields.Char("Access Key")
    secret_access_key = fields.Char("Secret Key")
    s3_bucket_name = fields.Char("BucketName")

    cloud_url = fields.Char('URL')
    cloud_username = fields.Char('Username')
    cloud_password = fields.Char('Password')

    @api.model
    def create(self, vals):
        vals = self.check_upload_path(vals)
        model_id = self.env['ir.model'].search([('model','=', self._name)])
        nextbackuptime = self.next_backup_time
        if not nextbackuptime:
            nextbackuptime = datetime.datetime.today() + datetime.timedelta(days=1)
        cron_id = self.env['ir.cron'].create({
            'name': 'Backup: ' + vals['name'],
            'model_id': model_id.id,
            'state': 'code',
            'user_id': 1,
            'interval_number': vals['schedule_number'],
            'interval_type': vals['schedule_frequently'],
            'nextcall': nextbackuptime,
            'priority': 100,
            'numbercall': -1,
            'active': vals['active'],
            'code': 'model.action_backup('+str(self.id)+')'
        })
        vals['cron_id'] = cron_id.id
        result = super(Configuration, self).create(vals)
        return result

    @api.multi
    def write(self, vals):
        self.ensure_one()
        vals = self.check_upload_path(vals)
        result = super(Configuration, self).write(vals)
        try:
            if self.cron_id:
                if 'interval_number' in vals:
                    self.cron_id.write({'interval_number': self.schedule_number,})
                if 'interval_type' in vals:
                    self.cron_id.write({'interval_type': self.schedule_frequently,})
                if 'active' in vals:
                    self.cron_id.write({'active': self.active})
                if 'name' in vals:
                    self.cron_id.write({'name': 'Backup: '+self.name})
        except:
            pass
        return result

    def unlink(self):
        cron_id = self.cron_id
        self.cron_id = False
        if cron_id:
            cron_id.unlink()
        result = super(Configuration, self).unlink()
        return result

    def check_upload_path(self, vals):
        if 'upload_path' in vals:
            vals['upload_path'] = vals['upload_path'].replace('\\', '/')
            vals['upload_path'] = ''.join(
                vals['upload_path'][i] for i in range(len(vals['upload_path'])-1)
                if (i != 0 and vals['upload_path'][i-1] != vals['upload_path'][i]) or vals['upload_path'][i] != '/' or (vals['upload_path'][i] == '/' and i == 0)
            )
            if len(vals['upload_path']):
                if '/' != vals['upload_path'][0]:
                    vals['upload_path'] = '/' + vals['upload_path']
                if '/' != vals['upload_path'][-1]:
                    vals['upload_path'] = vals['upload_path'] + '/'
            else:
                vals['upload_path'] = '/'
        return vals

    def set_show_s3(self):
        self.show_s3 = (self.backup_type == BackupTypes.s3.value[0])

    def set_show_dropbox(self):
        self.show_dropbox = (self.backup_type == BackupTypes.dropbox.value[0])

    def set_show_owncloud(self):
        self.show_owncloud = (self.backup_type == BackupTypes.owncloud.value[0])

    def set_show_access_key(self):
        self.show_access_key = (
            (self.backup_type == BackupTypes.s3.value[0])
            or (self.backup_type == BackupTypes.dropbox.value[0])
        )

    def set_show_secret_key(self):
        self.show_secret_key = (self.backup_type == BackupTypes.s3.value[0])

    def _compute_next_backup_time(self):
        if self.cron_id:
            self.next_backup_time = self.cron_id.nextcall

    @api.onchange('backup_type')
    def onchange_backup_type(self):
        self.set_show_s3()
        self.set_show_access_key()
        self.set_show_secret_key()
        self.set_show_owncloud()

    def action_backup(self, id):
        backup_ids = self.browse([id])
        for backup in backup_ids:
            backup.btn_action_backup()

    @api.multi
    def btn_action_backup(self):
        self.ensure_one()
        try:
            if self.backup_type == BackupTypes.s3.value[0]:
                self._backup_on_s3()
            elif self.backup_type == BackupTypes.dropbox.value[0]:
                self._backup_on_dropbox()
            elif self.backup_type == BackupTypes.google_drive.value[0]:
                self._backup_on_googledrive()
            elif self.backup_type == BackupTypes.owncloud.value[0]:
                self._backup_on_owncloud()
            self.send_email()
        except Exception as err:
            self.set_last_fields(err.args[0])
            self.message_post(err.args[0])
            self.send_email(success=False)

    def send_email(self, success=True):
        if ((success and self.success_mail.id is not False) or (not success and self.error_mail.id is not False)):
            template_name = 'backup_configuration_success_template' if success else 'backup_configuration_error_template'
            template = self.env.ref('automatic_backup.'+template_name)
            self.env['mail.template'].browse(template.id).send_mail(self.id, force_send=True)

    def _backup_on_s3(self):
        if self.access_key_id is False or self.secret_access_key is False:
            raise exceptions.MissingError("AWS S3: You need to add a AccessKey and a SecretAccessKey!")
        if self.s3_bucket_name is False:
            raise exceptions.MissingError("AWS S3: You need to add a BucketName!")

        client = boto3.client('s3', aws_access_key_id=self.access_key_id, aws_secret_access_key=self.secret_access_key)
        path, content = self.get_path_and_content()

        try:
            client.put_object(Bucket=self.s3_bucket_name, Body=content, Key=path)
        except botocore.exceptions.ClientError as client_err:
            raise exceptions.ValidationError(
                "AWS S3: " + client_err.response['Error']['Message'])
        else:
            message = ("AWS S3: No Error during upload. You can find the backup under the bucket {0} with the "
                      "name {1}".format(self.s3_bucket_name, path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def _backup_on_dropbox(self):
        dbx = dropbox.Dropbox(self.access_key_id)
        path, content = self.get_path_and_content()
        try:
            dbx.files_upload(content.read(), path)
        except dropbox_exceptions.AuthError:
            raise exceptions.ValidationError("Dropbox: Wrong Access Key!")
        else:
            message = ("Dropbox: No Error during upload. You can find the backup under the name {0}".format(path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def _backup_on_googledrive(self):
        pass

    def _backup_on_owncloud(self):
        oc = owncloud.Client(self.cloud_url)
        try:
            oc.login(self.cloud_username, self.cloud_password)
        except:
            raise exceptions.ValidationError("ownCloud: Check your Creds!")
        path, content = self.get_path_and_content()
        try:
            oc.put_file_contents(path, content.read())
        except Exception as err:
            if err.status_code == 404:
                raise exceptions.ValidationError("Folder not found!")
            raise err
        message = ("ownCloud: No Error during upload. You can find the backup under {0}".format(path))
        self.set_last_fields(message, path=path)
        self.message_post(message)

    def get_path_and_content(self):
        filename, content = self.get_backup()
        path = os.path.join(self.upload_path, filename)
        return path, content

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
