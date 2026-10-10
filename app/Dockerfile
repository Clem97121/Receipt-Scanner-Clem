# AWS Lambda image; one image serves all functions, Terraform picks the handler via image_config.command
FROM public.ecr.aws/lambda/python:3.12

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY app/requirements.txt ${LAMBDA_TASK_ROOT}/

RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt --target ${LAMBDA_TASK_ROOT}

COPY app/ ${LAMBDA_TASK_ROOT}/

# Default handler; the worker and migrate functions override it
CMD ["lambda_handlers.webhook"]
