// course-advisor-v2 — Week 5 infrastructure
// Deploys: App Service Plan (Linux, B1) + App Service (backend) + Static Web App (frontend)
// Usage: az deployment group create -g <resource-group> -f infra/main.bicep --parameters geminiApiKey=<key>

@description('Base name used to derive resource names (lowercase letters/numbers only)')
param appNameBase string = 'courseadvisor'

@description('Azure region for all resources. Must support Microsoft.Web/staticSites — eastus2, centralus, westus2, westeurope, eastasia.')
param location string = 'eastus2'

@description('Gemini API key for the backend. Pass via --parameters at deploy time — never stored in this file or committed to git.')
@secure()
param geminiApiKey string

@description('Python version for the App Service runtime')
param pythonVersion string = '3.14'

var uniqueSuffix = uniqueString(resourceGroup().id)
var appServicePlanName = '${appNameBase}-plan-${uniqueSuffix}'
var webAppName = '${appNameBase}-api-${uniqueSuffix}'
var staticWebAppName = '${appNameBase}-web-${uniqueSuffix}'

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  properties: {
    reserved: true // required for Linux plans
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|${pythonVersion}'
      appCommandLine: 'gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --timeout 120'
      alwaysOn: true
      appSettings: [
        {
          name: 'GEMINI_API_KEY'
          value: geminiApiKey
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ]
    }
  }
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

output backendUrl string = 'https://${webApp.properties.defaultHostName}'
output staticWebAppName string = staticWebApp.name
output staticWebAppDefaultHostname string = staticWebApp.properties.defaultHostname
