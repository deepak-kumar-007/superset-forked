# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import datetime
import json
import logging
from io import BytesIO
from typing import Any, Optional
from uuid import uuid4

import boto3

from superset import app
from superset.exceptions import SupersetErrorsException
from superset.reports.models import ReportRecipientType
from superset.reports.notifications.base import BaseNotification
from superset.reports.notifications.exceptions import NotificationError

logger = logging.getLogger(__name__)


class S3SubTypes:  # pylint: disable=too-few-public-methods
    """
    Defines different types of AWS S3 configurations.
    """

    S3_CRED = "AWS_S3_credentials"
    S3_CONFIG = "AWS_S3_pyconfig"
    S3_ROLE = "AWS_S3_IAM"


class S3Notification(BaseNotification):  # pylint: disable=too-few-public-methods
    # pylint: disable= too-many-arguments, invalid-name
    type = ReportRecipientType.S3

    def _get_inline_files(self) -> dict[Any, Any]:
        current_datetime = datetime.datetime.now()
        formatted_date = current_datetime.strftime("%Y-%m-%d")
        report_name = self._content.name
        name_prefix = f"{report_name}/{formatted_date}/"

        if self._content.csv:
            data = {
                f"{name_prefix}{report_name}-{str(uuid4())[:8]}.csv": self._content.csv
            }
            return data
        if self._content.screenshots:
            images = {
                f"{name_prefix}Screenshot-{str(uuid4())[:8]}.png": screenshot
                for screenshot in self._content.screenshots
            }
            return images
        return {}

    def _execute_s3_upload(
        self,
        file_body: dict[Any, Any],
        bucket_name: str,
        contentType: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ) -> None:
        for key, file in file_body.items():
            file = BytesIO(file)
            s3 = boto3.client(
                "s3",
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )
            s3.upload_fileobj(
                file,
                bucket_name,
                key,
                ExtraArgs={
                    "Metadata": {"Content-Disposition": "inline"},
                    "ContentType": contentType,
                },
            )

            logger.info(
                "Report sent to Aws S3 Bucket, notification content is %s",
                self._content.header_data,
            )

    def send(self) -> None:
        files = self._get_inline_files()
        file_type = "csv" if self._content.csv else "png"
        bucket_name = json.loads(self._recipient.recipient_config_json)["target"]
        s3_subtype = self._aws_configuration.aws_s3_types

        try:
            if s3_subtype == S3SubTypes.S3_CRED:
                aws_access_key_id = self._aws_configuration.aws_key
                aws_secret_access_key = self._aws_configuration.aws_secret_key

                self._execute_s3_upload(
                    file_body=files,
                    bucket_name=bucket_name,
                    contentType=file_type,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                )

            elif s3_subtype == S3SubTypes.S3_ROLE:
                self._execute_s3_upload(
                    file_body=files, bucket_name=bucket_name, contentType=file_type
                )

            elif s3_subtype == S3SubTypes.S3_CONFIG:
                aws_access_key_id = app.config["AWS_ACCESS_KEY"]
                aws_secret_access_key = app.config["AWS_SECRET_KEY"]

                self._execute_s3_upload(
                    file_body=files,
                    bucket_name=bucket_name,
                    contentType=file_type,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                )
            else:
                msg = (
                    f"Unsupported AWS S3 method, Must be {S3SubTypes.S3_CONFIG} | "
                    f"{S3SubTypes.S3_CRED} | {S3SubTypes.S3_ROLE}"
                )

                logger.error(msg)
        except SupersetErrorsException as ex:
            raise NotificationError(
                ";".join([error.message for error in ex.errors])
            ) from ex
        except Exception as ex:
            raise NotificationError(str(ex)) from ex
