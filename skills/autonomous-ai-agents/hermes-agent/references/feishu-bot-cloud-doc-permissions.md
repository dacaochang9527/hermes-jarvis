# Feishu Bot Cloud Document Permissions

Use this when the user wants Hermes/Feishu bot application identity to create reports, upload document assets, grant readers, and send document links to a Feishu group.

## Default architecture

Prefer application/bot-owned documents for automated reports:
1. Obtain `tenant_access_token` with the Feishu app credentials.
2. Create the report document as the app/bot.
3. Write content into the app-created document.
4. If needed, upload images/attachments as document assets and reference them from document blocks.
5. Grant read permission to the target group or specific users, or update link-sharing settings.
6. Send the document URL to the group via the bot message API.

This avoids requiring a user OAuth token for routine scheduled reports.

## Minimal permission set

For creating and editing modern Feishu docs (`docx`):
- `docx:document:create` — create new docx documents in cloud space.
- `docx:document:write_only` — add, delete, and update docx content/blocks.
- Alternative: `docx:document` if a broader create/read/edit permission is acceptable.

For uploading resources into a document:
- Permission named like “上传图片和附件到云文档中” — required by cloud-document asset APIs such as upload material / multipart upload material.
- Use this for images or attachments embedded inside doc blocks.

For uploading ordinary files into cloud drive rather than embedding assets in a doc:
- `drive:file` — upload/download files to cloud space.
- Avoid broader `drive:drive` unless the workflow truly needs broad drive file management.

For making the created document readable by humans:
- Permission named “添加云文档协作者” — add users/groups as document collaborators.
- If the workflow must manage existing collaborator state, request the broader “查看、新增、更新、删除云文档协作者”.
- To change link-sharing, external-sharing, comment policy, or public/password settings, request “修改云文档权限设置” and possibly “查看云文档权限设置”.

For sending the link to a group:
- `im:message:send_as_bot` — send messages as the bot.
- The bot must already be in the target group for group sends and for adding a group collaborator via app identity.

## Important tenant_access_token caveats

With `tenant_access_token`, the app can usually operate only on resources it created or resources where the app has been explicitly granted access. If the user wants the app to work inside an existing folder/document, first grant the app appropriate cloud-document access via the Feishu UI or by adding the bot to a group that has manage permission.

For app-created documents, the app identity is the cleanest owner for automation. After creation, grant the target group or user read permission before posting the link.

## Practical recommendation

For scheduled Feishu report documents, start with:
- `docx:document:create`
- `docx:document:write_only`
- “上传图片和附件到云文档中” only if images/attachments are embedded
- “添加云文档协作者”
- “修改云文档权限设置” only if link/public settings must be changed
- `im:message:send_as_bot`

Do not ask for full `drive:drive` or sensitive group-message scopes unless the workflow truly needs broad drive file management.

## Verified bot-owned online document workflow

Use this sequence when converting a local Markdown/report file into an online Feishu doc readable inside the company:
1. Load `FEISHU_APP_ID` and `FEISHU_APP_SECRET`, then obtain `tenant_access_token` from `POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`. Do not print secrets.
2. Create the doc with `POST /open-apis/docx/v1/documents` and a plain text `title`. Keep the returned `document_id`.
3. For Markdown/HTML reports, do **not** manually map Markdown into ad-hoc docx blocks unless there is no alternative. Feishu `docx` write APIs do not auto-render Markdown. First call the official converter `POST /open-apis/docx/v1/documents/blocks/convert` with `{"content_type":"markdown","content":"..."}`. This requires the permission “文本内容转换为云文档块” / `docx:document.block:convert`.
4. Insert the converted blocks with the nested-block API `POST /open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1`, passing `children_id` from `first_level_block_ids` and `descendants` from `blocks`. Before insertion, recursively remove table `merge_info` fields returned by the converter because they are read-only and can cause insert errors.
5. Only use `POST /open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children` for simple hand-built flat blocks, not for Markdown tables/lists/headings that need faithful formatting.
6. Check current public permission with `GET /open-apis/drive/v1/permissions/{document_id}/public?type=docx`.
7. Set company-link-readable with `PATCH /open-apis/drive/v1/permissions/{document_id}/public?type=docx` and the minimal payload `{"external_access": false, "link_share_entity": "tenant_readable"}`. This was verified to produce `link_share_entity=tenant_readable` and `external_access=false`.
8. Verify the final URL and title with `POST /open-apis/drive/v1/metas/batch_query?user_id_type=open_id`, using body `{"request_docs":[{"doc_token":"...","doc_type":"docx"}],"with_url":true}`. Prefer the metadata `url` host as the final link.
9. If the online doc was generated from a local Markdown report, immediately patch the local report metadata block near the top with a line like `> 飞书在线文档：https://...`, so the local source of truth points back to the retained online doc.
10. Return or send the final URL only after permission and metadata verification. If the document is later copied/recreated/retitled and the URL changes, update the local Markdown link to the final retained URL.

Pitfall: `FEISHU_DOMAIN` in a Hermes gateway `.env` may be a platform label such as `feishu`, not the Open Platform API base URL. For raw API scripts, prefer `https://open.feishu.cn` unless a valid HTTP(S) API base URL is configured.

For permission updates, avoid sending broad guessed payloads. A larger payload containing fields such as `security_entity`, `comment_entity`, `share_entity`, and `copy_entity` can fail with `99992402 field validation failed`; retry with the minimal field set needed for the goal.

## Maintaining bot-owned Feishu docs after creation

Use this when the user asks to delete, verify, or retitle app-created report documents:
1. Delete a docx by moving it to recycle bin with `DELETE /open-apis/drive/v1/files/{document_id}?type=docx`. A successful app-owned delete returns HTTP 200 with `code=0` and `msg=success`.
2. Verify document metadata with `POST /open-apis/drive/v1/metas/batch_query?user_id_type=open_id`, using body `{"request_docs":[{"doc_token":"...","doc_type":"docx"}],"with_url":true}`. Do not use the older/incorrect `/drive/v1/files/batch_query` shape for doc title verification.
3. If direct title update attempts on `docx` fail or are unsupported for the app identity, use the durable workaround: get root folder metadata via `GET /open-apis/drive/explorer/v2/root_folder/meta`, copy the doc with `POST /open-apis/drive/v1/files/{document_id}/copy?user_id_type=open_id` and body `{"name":"new title","type":"docx","folder_token":"root_token"}`, then apply the same public permission settings to the copy.
4. After the copy is verified by metadata title and URL, delete the old incorrectly titled docx. Return the new URL explicitly because copying changes the `document_id`.
5. Keep tenant hostnames from metadata (`url`) when reporting the final link; user-provided links may use a different visible host than the metadata URL returned by Open Platform.
