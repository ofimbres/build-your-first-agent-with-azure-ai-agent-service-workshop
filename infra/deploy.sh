#!/bin/bash

echo "Deploying the Azure resources..."

# Define resource group parameters
RG_LOCATION="eastus"
MODEL_NAME="gpt-4o"
MODEL_VERSION="2024-11-20"
AI_PROJECT_FRIENDLY_NAME="Agent Service Workshop"
MODEL_CAPACITY=140

# Deploy the Azure resources and save output to JSON
az deployment sub create \
  --name "azure-ai-agent-service-lab" \
  --location "$RG_LOCATION" \
  --template-file main.bicep \
  --parameters \
      aiProjectFriendlyName="$AI_PROJECT_FRIENDLY_NAME" \
      modelName="$MODEL_NAME" \
      modelCapacity="$MODEL_CAPACITY" \
      modelVersion="$MODEL_VERSION" \
      location="$RG_LOCATION" > output.json

# Parse the JSON file manually using grep and sed
if [ ! -f output.json ]; then
  echo "Error: output.json not found."
  exit -1
fi

PROJECTS_ENDPOINT=$(jq -r '.properties.outputs.projectsEndpoint.value' output.json)
RESOURCE_GROUP_NAME=$(jq -r '.properties.outputs.resourceGroupName.value' output.json)
SUBSCRIPTION_ID=$(jq -r '.properties.outputs.subscriptionId.value' output.json)
AI_SERVICE_NAME=$(jq -r '.properties.outputs.aiAccountName.value' output.json)
AI_PROJECT_NAME=$(jq -r '.properties.outputs.aiProjectName.value' output.json)
FUNCTION_APP_URL=$(jq -r '.properties.outputs.functionAppUrl.value' output.json)
BING_RESOURCE_NAME="groundingwithbingsearch"

BING_CONNECTION_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP_NAME/providers/Microsoft.CognitiveServices/accounts/$AI_SERVICE_NAME/projects/$AI_PROJECT_NAME/connections/$BING_RESOURCE_NAME"

if [ -z "$PROJECTS_ENDPOINT" ]; then
  echo "Error: projectsEndpoint not found. Possible deployment failure."
  exit -1
fi

ENV_FILE_PATH="../src/python/workshop/.env"

# Delete the file if it exists
[ -f "$ENV_FILE_PATH" ] && rm "$ENV_FILE_PATH"


# Write to the .env file
{
  echo "PROJECT_ENDPOINT=$PROJECTS_ENDPOINT"
  echo "AZURE_BING_CONNECTION_ID=$BING_CONNECTION_ID"
  echo "MODEL_DEPLOYMENT_NAME=\"$MODEL_NAME\""
  echo "FUNCTION_APP_ENDPOINT=$FUNCTION_APP_URL/api"
} > "$ENV_FILE_PATH"

CSHARP_PROJECT_PATH="../src/csharp/workshop/AgentWorkshop.Client/AgentWorkshop.Client.csproj"

# Set the user secrets for the C# project
dotnet user-secrets set "ConnectionStrings:AiAgentService" "$PROJECTS_ENDPOINT" --project "$CSHARP_PROJECT_PATH"
dotnet user-secrets set "Azure:ModelName" "$MODEL_NAME" --project "$CSHARP_PROJECT_PATH"
dotnet user-secrets set "Azure:BingConnectionId" "$BING_CONNECTION_ID" --project "$CSHARP_PROJECT_PATH"

# Register the Bing Search resource provider
echo "Attempting to register the Bing Search provider"

az provider register --namespace 'Microsoft.Bing'

# Check if the command succeeded based on its exit status
if [ $? -ne 0 ]; then
    echo "Bing Search registration FAILED. The attempt to register the Bing Search resource was unsuccessful, which means you cannot complete the Grounding with Bing Search lab."
    exit 1
fi

# Wait for a few seconds to allow Azure time to process the registration
sleep 10

# Check if the provider is registered successfully
provider_state=$(az provider show --namespace 'Microsoft.Bing' --query "registrationState" -o tsv)

if [ "$provider_state" != "Registered" ]; then
    echo "Bing Search registration FAILED. The attempt to register the Bing Search resource was unsuccessful, which means you cannot complete the Grounding with Bing Search lab."
    exit 1
fi

echo "Bing Search registration succeeded."

echo "Adding Azure AI Developer user role"

# Set Variables
subId=$(az account show --query id --output tsv)
objectId=$(az ad signed-in-user show --query id -o tsv)

az role assignment create --role "f6c7c914-8db3-469d-8ca1-694a8f32e121" \
                          --assignee-object-id "$objectId" \
                          --scope "subscriptions/$subId/resourceGroups/$RESOURCE_GROUP_NAME" \
                          --assignee-principal-type 'User'

# Check if the command failed
if [ $? -ne 0 ]; then
    echo "User role assignment failed."
    exit 1
fi

echo "User role assignment succeeded."

# Deploy Function App Code
echo "Deploying Function App code..."

# Get Function App name from outputs
FUNCTION_APP_NAME=$(jq -r '.properties.outputs.functionAppName.value' output.json 2>/dev/null)

if [ -n "$FUNCTION_APP_NAME" ] && [ "$FUNCTION_APP_NAME" != "null" ]; then
    echo "Deploying code to Function App: $FUNCTION_APP_NAME"
    
    # Prepare deployment package
    TEMP_DIR=$(mktemp -d)
    DEPLOY_DIR="$TEMP_DIR/function"
    
    mkdir -p "$DEPLOY_DIR"
    
    # Copy all function files
    FUNCTION_SOURCE_DIR="../src/shared/azure-function"
    cp -r "$FUNCTION_SOURCE_DIR"/* "$DEPLOY_DIR/"
    
    # Copy database
    DATABASE_PATH="../src/shared/database/contoso-sales.db"
    if [ -f "$DATABASE_PATH" ]; then
        echo "Including database..."
        cp "$DATABASE_PATH" "$DEPLOY_DIR/"
    fi
    
    # Install dependencies using Azure Functions structure
    echo "Installing dependencies..."
    cd "$DEPLOY_DIR"
    pip install --target="./.python_packages/lib/site-packages" -r requirements.txt
    
    # Create deployment package
    echo "Creating deployment package..."
    zip -r ../function.zip . -q
    
    # Deploy
    echo "Deploying function code..."
    az functionapp deployment source config-zip \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --name "$FUNCTION_APP_NAME" \
        --src "../function.zip" \
        --output none
    
    echo "Waiting for deployment..."
    sleep 20
    
    # Cleanup
    rm -rf "$TEMP_DIR"
    
    echo "Function App deployment complete!"
    echo "Test endpoints:"
    echo "   Health: $FUNCTION_APP_URL/health"
    echo "   Info: $FUNCTION_APP_URL/database-info"
else
    echo "Function App name not found in outputs, skipping code deployment"
fi

# Delete the output.json file
rm -f output.json

echo ""
echo "Deployment Complete!"
echo "====================="
echo "Azure AI Foundry resources deployed"
echo "Function App deployed and configured"
echo "Environment files created"
echo ""