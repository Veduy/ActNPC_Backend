Finalize the parsed CommandDict.

Rules:
- Expand all/every item requests into one get_item/fetch/put_item step per matching Unity item.
- Preserve explicit step.count unless expanding all/every.
- Preserve user order.
- Use Unity context object_id values in object_id; also mirror to legacy object for compatibility.
- Keep object_name as the concise object/place name. Repeated item steps may reuse the same type id.
- Do not add fields outside the schema.
- Legacy top-level fields mirror the first final step.
