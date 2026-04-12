@{
    Rules = @{
        PSReviewUnusedParameter = @{
            CommandsToTraverse = @(
                'Describe'
                'Context'
                'It'
                'BeforeAll'
                'BeforeDiscovery'
                'AfterAll'
            )
        }
    }
}
